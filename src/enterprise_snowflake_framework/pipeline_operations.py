from __future__ import annotations

from .pipeline_model import PipelineNames


def render_task_sql(pattern: str, names: PipelineNames, project_code: str) -> str:
    if pattern == "custom":
        return (
            f"-- {names.dataset_key} {names.version}: custom task/orchestration.\n"
            "-- Use a Snowflake Task only when it fits this dataset's readiness model.\n"
        )
    when = f"\n    WHEN SYSTEM$STREAM_HAS_DATA('{names.stream}')" if names.stream else ""
    readiness = (
        "-- Triggered by unconsumed stream data."
        if names.stream
        else "-- No readiness signal is assumed. Add SCHEDULE/AFTER/control-event wiring before activation."
    )
    return f"""{readiness}
-- This version owns a new task name. CREATE is intentionally fail-closed: an unexpected
-- pre-existing task is an ownership conflict and must not be silently replaced or suspended.
-- Snowflake creates new tasks suspended. Validation and activation are explicit.
-- One task run applies the transformation and then records dataset-local structural DQ evidence.
CREATE TASK {names.task}
    WAREHOUSE = WH_{project_code}_TRANSFORM{when}
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
    if pattern == "custom":
        apply_value = "NULL"
        task_value = "NULL"
        stream_value = "NULL"
    else:
        apply_value = f"'{names.apply_procedure}'"
        task_value = f"'{names.task}'"
        stream_value = "NULL" if names.stream is None else f"'{names.stream}'"
    return f"""-- Register operational identity. This does not route transformation logic.
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
    V.UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    DATASET_ID, VERSION, STATUS, HISTORY_RELATION, CURRENT_RELATION,
    APPLY_OBJECT, TASK_OBJECT, STREAM_OBJECT, DEPLOYED_AT
) VALUES (
    S.DATASET_ID, S.VERSION, S.STATUS, {history}, {current},
    {apply_value}, {task_value}, {stream_value}, CURRENT_TIMESTAMP()
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
    paths = [
        f"{base}/001_objects.sql",
        f"{base}/010_apply.sql",
        f"{base}/015_replay.sql",
        f"{base}/020_validate.sql",
        f"{base}/030_task.sql",
        f"{base}/040_register.sql",
    ]
    if not candidate:
        paths.append(f"{base}/050_publish.sql")
    return "\n".join(paths) + "\n"


def render_version_yaml(names: PipelineNames, *, candidate: bool) -> str:
    initial = "development" if candidate else "active"
    return (
        "schema_version: 1\n\n"
        "version:\n"
        f"  dataset: {names.dataset_key}\n"
        f"  id: {names.version}\n"
        f"  initial_status: {initial}\n"
        "  activation: explicit\n"
    )


def _published_replacement(pattern: str, names: PipelineNames) -> str:
    if pattern == "scd2":
        assert names.history_relation and names.published_history and names.published_current
        return f"""CREATE OR REPLACE VIEW {names.published_history} COPY GRANTS AS
SELECT * FROM {names.history_relation};

CREATE OR REPLACE VIEW {names.published_current} COPY GRANTS AS
SELECT * FROM {names.history_relation}
WHERE IS_ACTIVE = TRUE;"""
    assert names.physical_relation and names.published_relation
    return f"""CREATE OR REPLACE VIEW {names.published_relation} COPY GRANTS AS
SELECT * FROM {names.physical_relation};"""


def render_release_sql(pattern: str, names_from: PipelineNames, names_to: PipelineNames) -> tuple[str, str]:
    if pattern == "custom":
        raise ValueError("custom pipelines require domain-authored activation and rollback SQL")

    def script(old: PipelineNames, new: PipelineNames) -> str:
        if new.stream:
            prepare_new = f"""-- Candidate processing is started before publication. If publication later fails,
-- the previous implementation still serves consumers and continues processing.
ALTER TASK {new.task} RESUME;
"""
        else:
            prepare_new = (
                f"-- {new.task} has no readiness schedule by default. Ensure the candidate snapshot is\n"
                "-- already rebuilt and validated before publication; no implicit task activation is attempted.\n"
            )
        publish_sql = _published_replacement(pattern, new)
        return f"""-- Explicit cutover: {new.dataset_key} {old.version} -> {new.version}
-- Review VERSION_VALIDATION and candidate DQ evidence before running. This file is never auto-executed by scaffold.
-- Stable consumer views use COPY GRANTS so explicit non-OWNERSHIP privileges survive replacement.
-- Snowflake DDL commits independently. If a later step fails, keep the old task running, inspect state,
-- and use the generated rollback/corrective operation rather than blindly retrying partial cutover SQL.

{prepare_new}
{publish_sql}

UPDATE CONTROL.DATASET_VERSION
SET STATUS = 'ACTIVE', ACTIVATED_AT = CURRENT_TIMESTAMP(), RETIRED_AT = NULL, UPDATED_AT = CURRENT_TIMESTAMP()
WHERE DATASET_ID = '{new.dataset_key}' AND VERSION = '{new.version}';

UPDATE CONTROL.DATASET
SET ACTIVE_VERSION = '{new.version}', CANDIDATE_VERSION = NULL, UPDATED_AT = CURRENT_TIMESTAMP()
WHERE DATASET_ID = '{new.dataset_key}';

UPDATE CONTROL.DATASET_VERSION
SET STATUS = 'RETIRED', RETIRED_AT = CURRENT_TIMESTAMP(), UPDATED_AT = CURRENT_TIMESTAMP()
WHERE DATASET_ID = '{new.dataset_key}' AND VERSION = '{old.version}';

-- Retire old processing last. An earlier publication/control failure must not suspend the
-- previously active pipeline as its first side effect.
ALTER TASK {old.task} SUSPEND;
"""

    return script(names_from, names_to), script(names_to, names_from)
