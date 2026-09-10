from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 691200  # Snowflake Task interval maximum: 8 days.
_OPERATION_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_MIGRATION_PATH = "control_plane/sql/130_health_evaluation_cadence.sql"
_TASK_NAME = "CONTROL.EVALUATE_DOMAIN_HEALTH_TASK"


@dataclass(frozen=True)
class HealthCadenceScriptsResult:
    operation_id: str
    interval_seconds: int
    resume_after: bool
    destination: Path
    created: bool
    files: tuple[Path, ...]


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _validate_request(operation_id: str, interval_seconds: int, reason: str) -> None:
    if not _OPERATION_ID.fullmatch(operation_id):
        raise ValueError("operation_id must match ^[a-z][a-z0-9_-]{1,63}$")
    if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int):
        raise ValueError("interval_seconds must be an integer")
    if not MIN_INTERVAL_SECONDS <= interval_seconds <= MAX_INTERVAL_SECONDS:
        raise ValueError(
            f"interval_seconds must be between {MIN_INTERVAL_SECONDS} and "
            f"{MAX_INTERVAL_SECONDS} (10 seconds through 8 days)"
        )
    if not reason or not reason.strip():
        raise ValueError("reason is required for an auditable health cadence change")
    if len(reason) > 1000:
        raise ValueError("reason must be 1000 characters or fewer")


def _preflight_sql(operation_id: str) -> str:
    operation = _sql_literal(operation_id)
    return f"""-- Read-only preflight for domain health evaluation cadence change {operation_id}.
-- Migration 130 must already be applied in this environment.

SELECT
    OPERATION_ID,
    INTERVAL_SECONDS,
    REQUESTED_FINAL_STATE,
    STATUS,
    STARTED_AT,
    COMPLETED_AT,
    OPERATOR,
    REASON
FROM CONTROL.HEALTH_EVALUATION_CHANGE
WHERE OPERATION_ID = {operation};

-- Confirm the Framework health task exists and review its current schedule/state.
SHOW TASKS LIKE 'EVALUATE_DOMAIN_HEALTH_TASK' IN SCHEMA CONTROL;
"""


def _operation_sql(
    *, operation_id: str, interval_seconds: int, reason: str, resume_after: bool
) -> str:
    operation = _sql_literal(operation_id)
    reason_sql = _sql_literal(reason.strip())
    final_state = "STARTED" if resume_after else "SUSPENDED"
    resume_sql = (
        f"ALTER TASK {_TASK_NAME} RESUME;"
        if resume_after
        else "-- Explicit operator choice: leave the health evaluation Task suspended."
    )
    return f"""-- Configure the domain health evaluation cadence.
-- Generated for review. `esf` never executes this file.
-- Requires applied migration 130_health_evaluation_cadence.sql.
--
-- Snowflake interval schedules are re-anchored when the schedule is changed/resumed.
-- This operation deliberately suspends before ALTER TASK for compatibility with the
-- fail-closed singleton Task modification contract.

EXECUTE IMMEDIATE $$
DECLARE
    V_EXISTING NUMBER DEFAULT 0;
    E_DUPLICATE_OPERATION EXCEPTION (-20130, 'Health cadence operation id already exists. Use a new reviewed operation id.');
BEGIN
    V_EXISTING := (
        SELECT COUNT(*)
        FROM CONTROL.HEALTH_EVALUATION_CHANGE
        WHERE OPERATION_ID = {operation}
    );
    IF (V_EXISTING <> 0) THEN
        RAISE E_DUPLICATE_OPERATION;
    END IF;
END;
$$;

-- STARTED is written before Task DDL. If a later statement fails, leave this row as
-- evidence of a partial operation; inspect Task state before creating a new operation.
INSERT INTO CONTROL.HEALTH_EVALUATION_CHANGE (
    OPERATION_ID,
    TASK_NAME,
    INTERVAL_SECONDS,
    REQUESTED_FINAL_STATE,
    REASON,
    STATUS,
    STARTED_AT,
    OPERATOR
)
SELECT
    {operation},
    '{_TASK_NAME}',
    {interval_seconds},
    '{final_state}',
    {reason_sql},
    'STARTED',
    CURRENT_TIMESTAMP(),
    CURRENT_USER();

ALTER TASK {_TASK_NAME} SUSPEND;
ALTER TASK {_TASK_NAME} SET SCHEDULE = '{interval_seconds} SECONDS';
{resume_sql}

UPDATE CONTROL.HEALTH_EVALUATION_CHANGE
SET STATUS = 'SUCCEEDED',
    COMPLETED_AT = CURRENT_TIMESTAMP()
WHERE OPERATION_ID = {operation}
  AND STATUS = 'STARTED';
"""


def _postflight_sql(operation_id: str) -> str:
    operation = _sql_literal(operation_id)
    return f"""-- Verify both the recorded operation and Snowflake's actual Task state/schedule.
SELECT
    OPERATION_ID,
    TASK_NAME,
    INTERVAL_SECONDS,
    REQUESTED_FINAL_STATE,
    STATUS,
    STARTED_AT,
    COMPLETED_AT,
    OPERATOR,
    REASON
FROM CONTROL.HEALTH_EVALUATION_CHANGE
WHERE OPERATION_ID = {operation};

SELECT *
FROM CONTROL.HEALTH_EVALUATION_CONFIG_V;

SHOW TASKS LIKE 'EVALUATE_DOMAIN_HEALTH_TASK' IN SCHEMA CONTROL;
"""


def generate_health_cadence_scripts(
    *,
    project_root: Path,
    operation_id: str,
    interval_seconds: int,
    reason: str,
    resume_after: bool,
    output_root: Path | None = None,
) -> HealthCadenceScriptsResult:
    project_root = project_root.resolve()
    _validate_request(operation_id, interval_seconds, reason)

    migration = project_root / _MIGRATION_PATH
    if not migration.is_file():
        raise FileNotFoundError(
            f"Framework health cadence migration not found: {migration}. "
            "Run `esf init-project` with Framework 0.24+ before generating this operation."
        )

    root = (output_root or project_root / "operations" / "health").resolve()
    destination = root / operation_id
    if destination.exists():
        return HealthCadenceScriptsResult(
            operation_id=operation_id,
            interval_seconds=interval_seconds,
            resume_after=resume_after,
            destination=destination,
            created=False,
            files=(),
        )

    final_state = "STARTED" if resume_after else "SUSPENDED"
    readme = f"""# Domain health cadence change: {operation_id}

Requested interval: `{interval_seconds}` seconds  
Requested final Task state: `{final_state}`  
Reason: {reason.strip()}

This is a reviewed operational change, not logical dataset SLA configuration.

Required sequence:

1. Ensure `control_plane/sql/130_health_evaluation_cadence.sql` is applied in the target environment.
2. Run `preflight.sql` and inspect the current `CONTROL.EVALUATE_DOMAIN_HEALTH_TASK` schedule/state.
3. Review `operation.sql`. It writes `STARTED`, suspends the Task, changes the interval, and {'resumes it' if resume_after else 'leaves it suspended'}.
4. Run `postflight.sql` and verify Snowflake's actual Task state/schedule as well as the audit row.

If the operation fails after the `STARTED` row is written, do not blindly rerun it. Inspect the Task and partial DDL state, then use a new operation id for an explicitly reviewed correction.

The Framework never rewrites this operation directory after creation.
"""
    files = {
        "README.md": readme,
        "preflight.sql": _preflight_sql(operation_id),
        "operation.sql": _operation_sql(
            operation_id=operation_id,
            interval_seconds=interval_seconds,
            reason=reason,
            resume_after=resume_after,
        ),
        "postflight.sql": _postflight_sql(operation_id),
    }

    destination.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []
    for filename, text in files.items():
        path = destination / filename
        path.write_text(text, encoding="utf-8")
        paths.append(path)

    return HealthCadenceScriptsResult(
        operation_id=operation_id,
        interval_seconds=interval_seconds,
        resume_after=resume_after,
        destination=destination,
        created=True,
        files=tuple(paths),
    )
