from __future__ import annotations

from .execution_model import VersionExecution, render_version_yaml as _render_version_yaml
from .pipeline_model import PipelineNames


def render_task_sql(pattern: str, names: PipelineNames, project_code: str) -> str:
    if names.execution_model != "stream_task":
        raise ValueError("Task SQL is only valid for execution_model=stream_task")
    if pattern == "custom" or not names.task:
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
    assert names.apply_procedure and names.validate_procedure
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
    return f"""-- Register operational identity. This does not route transformation logic.
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


def _prepare_runtime(names: PipelineNames) -> str:
    if names.execution_model == "stream_task":
        if names.stream and names.task:
            return f"""-- Candidate processing is started before publication. If publication later fails,
-- the previous implementation still serves consumers and continues processing.
ALTER TASK {names.task} RESUME;
"""
        return "-- Stream/Task implementation has no automatic readiness schedule; ensure candidate data is current before publication.\n"
    if names.execution_model == "dynamic_table":
        assert names.dynamic_table
        return f"""-- Force a candidate refresh before switching the stable consumer view.
-- TARGET_LAG remains a best-effort staleness target rather than a release gate.
ALTER DYNAMIC TABLE {names.dynamic_table} REFRESH;
"""
    if names.execution_model == "batch_sql":
        return "-- Batch SQL implementation has no scheduler. Run its reviewed apply/validate path before publication.\n"
    return "-- Custom implementation: complete the domain-owned readiness action before publication.\n"


def _retire_runtime(names: PipelineNames) -> str:
    if names.execution_model == "stream_task" and names.task:
        return f"ALTER TASK {names.task} SUSPEND;"
    if names.execution_model == "dynamic_table" and names.dynamic_table:
        return f"ALTER DYNAMIC TABLE {names.dynamic_table} SUSPEND;"
    if names.execution_model == "batch_sql":
        return "-- Batch SQL implementation has no scheduler to suspend."
    return "-- Custom implementation: retire the domain-owned runtime explicitly."


def render_release_sql(pattern: str, names_from: PipelineNames, names_to: PipelineNames) -> tuple[str, str]:
    if pattern == "custom":
        raise ValueError("custom pipelines require domain-authored activation and rollback SQL")

    def script(old: PipelineNames, new: PipelineNames) -> str:
        prepare_new = _prepare_runtime(new)
        publish_sql = _published_replacement(pattern, new)
        retire_old = _retire_runtime(old)
        return f"""-- Explicit cutover: {new.dataset_key} {old.version} ({old.execution_model}) -> {new.version} ({new.execution_model})
-- Review VERSION_VALIDATION and candidate DQ evidence before running. This file is never auto-executed by scaffold.
-- Stable consumer views use COPY GRANTS so explicit non-OWNERSHIP privileges survive replacement.
-- Snowflake DDL commits independently. If a later step fails, keep the old runtime available, inspect state,
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

-- Retire old processing last. An earlier publication/control failure must not stop the
-- previously active implementation as its first side effect.
{retire_old}
"""

    return script(names_from, names_to), script(names_to, names_from)
