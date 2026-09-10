from __future__ import annotations

from .execution_model import VersionExecution, render_version_yaml as _render_version_yaml
from .pipeline_model import PipelineNames
from .release_operations import render_release_sql


def render_task_sql(
    pattern: str,
    names: PipelineNames,
    project_code: str,
    *,
    execution: VersionExecution | None = None,
) -> str:
    if names.execution_model != "stream_task":
        raise ValueError("Task SQL is only valid for execution_model=stream_task")
    if execution is not None and execution.execution_model != "stream_task":
        raise ValueError("Task execution config requires execution_model=stream_task")
    if pattern == "custom" or not names.task:
        return (
            f"-- {names.dataset_key} {names.version}: custom task/orchestration.\n"
            "-- Use a Snowflake Task only when it fits this dataset's readiness model.\n"
        )

    task = execution.task if execution is not None else None
    warehouse = task.warehouse if task is not None else f"WH_{project_code}_TRANSFORM"
    properties = [f"    WAREHOUSE = {warehouse}"]
    if task is not None and task.minimum_trigger_interval_seconds is not None:
        properties.append(
            "    USER_TASK_MINIMUM_TRIGGER_INTERVAL_IN_SECONDS = "
            f"{task.minimum_trigger_interval_seconds}"
        )
    if task is not None and task.timeout_seconds is not None:
        properties.append(f"    USER_TASK_TIMEOUT_MS = {task.timeout_seconds * 1000}")
    if task is not None and task.suspend_after_failures is not None:
        properties.append(
            f"    SUSPEND_TASK_AFTER_NUM_FAILURES = {task.suspend_after_failures}"
        )
    if task is not None and task.error_integration is not None:
        properties.append(f"    ERROR_INTEGRATION = {task.error_integration}")
    if names.stream:
        properties.append(f"    WHEN SYSTEM$STREAM_HAS_DATA('{names.stream}')")

    readiness = (
        "-- Triggered by unconsumed stream data."
        if names.stream
        else "-- No readiness signal is assumed. Add SCHEDULE/AFTER/control-event wiring before activation."
    )
    assert names.apply_procedure and names.validate_procedure
    task_properties = "\n".join(properties)
    return f"""{readiness}
-- Operational settings below belong to this implementation version, not to the logical dataset SLA.
-- This version owns a new task name. CREATE is intentionally fail-closed: an unexpected
-- pre-existing task is an ownership conflict and must not be silently replaced or suspended.
-- Snowflake creates new tasks suspended. Validation and activation are explicit.
-- One task run applies the transformation and then records dataset-local structural DQ evidence.
CREATE TASK {names.task}
{task_properties}
AS
BEGIN
    CALL {names.apply_procedure}();
    CALL {names.validate_procedure}();
END;

-- Triggered task activation after validation:
-- ALTER TASK {names.task} RESUME;
-- A task without SCHEDULE/AFTER/WHEN can still be tested explicitly with:
-- EXECUTE TASK {names.task};
"""


def _candidate_registration_guard(names: PipelineNames) -> str:
    return f"""-- Candidate registration is fail-closed. A second candidate must not silently
-- replace DATASET.CANDIDATE_VERSION, and a retired/active version must not be re-registered.
EXECUTE IMMEDIATE $$
DECLARE
    V_DATASET_COUNT NUMBER DEFAULT 0;
    V_ACTIVE_VERSION VARCHAR;
    V_CANDIDATE_VERSION VARCHAR;
    V_ACTIVE_STATUS_COUNT NUMBER DEFAULT 0;
    V_ACTIVE_POINTER_MATCH_COUNT NUMBER DEFAULT 0;
    V_INCOMING_STATUS VARCHAR;
    V_OTHER_DEPLOYED_COUNT NUMBER DEFAULT 0;
    E_NO_ACTIVE EXCEPTION (-20030, 'Candidate registration requires one existing active dataset.');
    E_ACTIVE_INVARIANT EXCEPTION (-20031, 'Candidate registration requires exactly one ACTIVE version matching ACTIVE_VERSION.');
    E_SAME_AS_ACTIVE EXCEPTION (-20032, 'Candidate version must differ from ACTIVE_VERSION.');
    E_CANDIDATE_CONFLICT EXCEPTION (-20033, 'Another candidate is already registered for this dataset.');
    E_VERSION_STATE_CONFLICT EXCEPTION (-20034, 'Candidate version is already ACTIVE or RETIRED.');
BEGIN
    V_DATASET_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET
        WHERE DATASET_ID = '{names.dataset_key}'
          AND ACTIVE_VERSION IS NOT NULL
    );
    IF (V_DATASET_COUNT <> 1) THEN
        RAISE E_NO_ACTIVE;
    END IF;

    SELECT ACTIVE_VERSION, CANDIDATE_VERSION
      INTO :V_ACTIVE_VERSION, :V_CANDIDATE_VERSION
    FROM CONTROL.DATASET
    WHERE DATASET_ID = '{names.dataset_key}';

    V_ACTIVE_STATUS_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{names.dataset_key}'
          AND UPPER(COALESCE(STATUS, '')) = 'ACTIVE'
    );
    V_ACTIVE_POINTER_MATCH_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{names.dataset_key}'
          AND VERSION = :V_ACTIVE_VERSION
          AND UPPER(COALESCE(STATUS, '')) = 'ACTIVE'
    );
    IF (V_ACTIVE_STATUS_COUNT <> 1 OR V_ACTIVE_POINTER_MATCH_COUNT <> 1) THEN
        RAISE E_ACTIVE_INVARIANT;
    END IF;

    IF (V_ACTIVE_VERSION = '{names.version}') THEN
        RAISE E_SAME_AS_ACTIVE;
    END IF;

    IF (V_CANDIDATE_VERSION IS NOT NULL AND V_CANDIDATE_VERSION <> '{names.version}') THEN
        RAISE E_CANDIDATE_CONFLICT;
    END IF;

    V_OTHER_DEPLOYED_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{names.dataset_key}'
          AND UPPER(COALESCE(STATUS, '')) = 'DEPLOYED'
          AND VERSION <> '{names.version}'
    );
    IF (V_OTHER_DEPLOYED_COUNT > 0) THEN
        RAISE E_CANDIDATE_CONFLICT;
    END IF;

    V_INCOMING_STATUS := (
        SELECT MAX(STATUS)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{names.dataset_key}'
          AND VERSION = '{names.version}'
    );
    IF (UPPER(COALESCE(V_INCOMING_STATUS, 'DEPLOYED')) IN ('ACTIVE', 'RETIRED')) THEN
        RAISE E_VERSION_STATE_CONFLICT;
    END IF;
END;
$$;
"""


def render_register_sql(pattern: str, names: PipelineNames, *, owner: str, candidate: bool) -> str:
    if pattern == "scd2":
        published = names.published_current or ""
        history = f"'{names.history_relation}'"
        current = f"'{names.current_relation}'"
    elif pattern == "custom":
        published = f"SILVER.{names.object_base}"
        history = "NULL"
        current = "NULL"
    else:
        published = names.published_relation or ""
        history = "NULL"
        current = f"'{names.physical_relation}'"
    active_insert = "NULL" if candidate else f"'{names.version}'"
    candidate_insert = f"'{names.version}'" if candidate else "NULL"
    version_update = (
        f"D.CANDIDATE_VERSION = '{names.version}',"
        if candidate
        else f"D.ACTIVE_VERSION = COALESCE(D.ACTIVE_VERSION, '{names.version}'),"
    )
    version_status = "DEPLOYED" if candidate else "ACTIVE"
    apply_value = f"'{names.apply_procedure}'" if names.apply_procedure else "NULL"
    task_value = f"'{names.task}'" if names.task else "NULL"
    stream_value = f"'{names.stream}'" if names.stream else "NULL"
    if names.execution_model == "dynamic_table":
        primary_runtime = f"'{names.dynamic_table}'"
    elif names.execution_model == "stream_task":
        primary_runtime = task_value
    elif names.execution_model == "batch_sql":
        primary_runtime = apply_value
    else:
        primary_runtime = "NULL"
    guard = _candidate_registration_guard(names) + "\n" if candidate else ""
    return f"""{guard}-- Register operational identity. This does not route transformation logic.
-- PATTERN belongs to the logical dataset; EXECUTION_MODEL belongs to this implementation version.
MERGE INTO CONTROL.DATASET D
USING (
    SELECT
        '{names.dataset_key}' AS DATASET_ID,
        '{names.source_id}' AS SOURCE_ID,
        '{names.dataset_id}' AS DATASET_NAME,
        '{owner}' AS OWNER,
        '{pattern}' AS PATTERN,
        '{names.bronze_relation}' AS BRONZE_RELATION,
        '{published}' AS PUBLISHED_SILVER_RELATION
) S
ON D.DATASET_ID = S.DATASET_ID
WHEN MATCHED THEN UPDATE SET
    D.OWNER = S.OWNER,
    D.PATTERN = S.PATTERN,
    D.BRONZE_RELATION = S.BRONZE_RELATION,
    D.PUBLISHED_SILVER_RELATION = S.PUBLISHED_SILVER_RELATION,
    {version_update}
    D.UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    DATASET_ID, SOURCE_ID, DATASET_NAME, OWNER, PATTERN, ENABLED,
    BRONZE_RELATION, PUBLISHED_SILVER_RELATION, ACTIVE_VERSION, CANDIDATE_VERSION
) VALUES (
    S.DATASET_ID, S.SOURCE_ID, S.DATASET_NAME, S.OWNER, S.PATTERN, TRUE,
    S.BRONZE_RELATION, S.PUBLISHED_SILVER_RELATION, {active_insert}, {candidate_insert}
);

MERGE INTO CONTROL.DATASET_VERSION V
USING (
    SELECT
        '{names.dataset_key}' AS DATASET_ID,
        '{names.version}' AS VERSION,
        '{version_status}' AS STATUS
) S
ON V.DATASET_ID = S.DATASET_ID AND V.VERSION = S.VERSION
WHEN MATCHED THEN UPDATE SET
    V.STATUS = IFF(V.STATUS = 'ACTIVE', 'ACTIVE', S.STATUS),
    V.HISTORY_RELATION = {history},
    V.CURRENT_RELATION = {current},
    V.APPLY_OBJECT = {apply_value},
    V.TASK_OBJECT = {task_value},
    V.STREAM_OBJECT = {stream_value},
    V.EXECUTION_MODEL = '{names.execution_model}',
    V.PRIMARY_RUNTIME_OBJECT = {primary_runtime},
    V.UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    DATASET_ID, VERSION, STATUS, HISTORY_RELATION, CURRENT_RELATION,
    APPLY_OBJECT, TASK_OBJECT, STREAM_OBJECT, EXECUTION_MODEL, PRIMARY_RUNTIME_OBJECT, DEPLOYED_AT
) VALUES (
    S.DATASET_ID, S.VERSION, S.STATUS, {history}, {current},
    {apply_value}, {task_value}, {stream_value}, '{names.execution_model}', {primary_runtime}, CURRENT_TIMESTAMP()
);
"""


def render_publish_sql(pattern: str, names: PipelineNames, *, candidate: bool) -> str:
    if candidate:
        return f"""-- Candidate {names.version} is intentionally not published.
-- Validate it first, then use an explicit release script to switch stable consumer objects.
"""
    if pattern == "custom":
        return (
            f"-- {names.dataset_key}: custom published contract.\n"
            "-- Define the stable SILVER consumer object explicitly.\n"
        )
    if pattern == "scd2":
        assert names.history_relation and names.published_history and names.published_current
        return f"""-- Initial publication is create-only. If the stable name unexpectedly exists,
-- fail rather than replace an object whose ownership or grants are unknown.
CREATE VIEW {names.published_history} AS
SELECT *
FROM {names.history_relation};

CREATE VIEW {names.published_current} AS
SELECT *
FROM {names.history_relation}
WHERE IS_ACTIVE = TRUE;
"""
    assert names.physical_relation and names.published_relation
    return f"""-- Initial publication is create-only. If the stable name unexpectedly exists,
-- fail rather than replace an object whose ownership or grants are unknown.
CREATE VIEW {names.published_relation} AS
SELECT *
FROM {names.physical_relation};
"""


def render_deploy_fragment(names: PipelineNames, *, candidate: bool) -> str:
    base = f"silver_processing/{names.source_id}/{names.dataset_id}"
    if candidate:
        base += f"/versions/{names.version}"
    if names.execution_model == "dynamic_table":
        filenames = ["001_dynamic_table.sql", "020_validate.sql", "040_register.sql"]
    elif names.execution_model == "batch_sql":
        filenames = ["001_objects.sql", "010_apply.sql", "015_replay.sql", "020_validate.sql", "040_register.sql"]
    elif names.execution_model == "custom":
        filenames = ["001_objects.sql", "040_register.sql"]
    else:
        filenames = ["001_objects.sql", "010_apply.sql", "015_replay.sql", "020_validate.sql", "030_task.sql", "040_register.sql"]
    if not candidate:
        filenames.append("050_publish.sql")
    return "\n".join(f"{base}/{name}" for name in filenames) + "\n"


def render_version_yaml(names: PipelineNames, *, candidate: bool, execution: VersionExecution | None = None) -> str:
    execution = execution or VersionExecution(names.execution_model)
    return _render_version_yaml(
        dataset_key=names.dataset_key,
        version=names.version,
        candidate=candidate,
        execution=execution,
    )
