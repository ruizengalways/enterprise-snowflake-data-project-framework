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


def _candidate_registration_guard(names: PipelineNames) -> str:
    return f"""-- Candidate registration is fail-closed. A second candidate must not silently
-- replace DATASET.CANDIDATE_VERSION, and a retired/active version must not be re-registered.
EXECUTE IMMEDIATE $$
DECLARE
    V_DATASET_COUNT NUMBER DEFAULT 0;
    V_ACTIVE_VERSION VARCHAR;
    V_CANDIDATE_VERSION VARCHAR;
    V_INCOMING_STATUS VARCHAR;
    V_OTHER_DEPLOYED_COUNT NUMBER DEFAULT 0;
    E_NO_ACTIVE EXCEPTION (-20030, 'Candidate registration requires one existing active dataset.');
    E_SAME_AS_ACTIVE EXCEPTION (-20031, 'Candidate version must differ from ACTIVE_VERSION.');
    E_CANDIDATE_CONFLICT EXCEPTION (-20032, 'Another candidate is already registered for this dataset.');
    E_VERSION_STATE_CONFLICT EXCEPTION (-20033, 'Candidate version is already ACTIVE or RETIRED.');
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


def _published_match_query(pattern: str, names: PipelineNames) -> tuple[int, str]:
    if pattern == "scd2":
        assert names.history_relation and names.published_history and names.published_current
        history_view = names.published_history.split(".", 1)[1]
        current_view = names.published_current.split(".", 1)[1]
        relation = names.history_relation.upper()
        return 2, f"""SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.VIEWS
        WHERE TABLE_SCHEMA = 'SILVER'
          AND (
                (TABLE_NAME = '{history_view}' AND POSITION('{relation}' IN UPPER(COALESCE(VIEW_DEFINITION, ''))) > 0)
             OR (TABLE_NAME = '{current_view}' AND POSITION('{relation}' IN UPPER(COALESCE(VIEW_DEFINITION, ''))) > 0)
          )"""
    assert names.physical_relation and names.published_relation
    published_view = names.published_relation.split(".", 1)[1]
    relation = names.physical_relation.upper()
    return 1, f"""SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.VIEWS
        WHERE TABLE_SCHEMA = 'SILVER'
          AND TABLE_NAME = '{published_view}'
          AND POSITION('{relation}' IN UPPER(COALESCE(VIEW_DEFINITION, ''))) > 0"""


def _sql_string(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _render_activate_script(
    pattern: str,
    old: PipelineNames,
    new: PipelineNames,
    *,
    allow_review_required: bool,
    operator_reason: str | None,
) -> str:
    prepare_new = _prepare_runtime(new)
    publish_sql = _published_replacement(pattern, new)
    retire_old = _retire_runtime(old)
    expected_views, published_match_query = _published_match_query(pattern, new)
    allow = "TRUE" if allow_review_required else "FALSE"
    reason = _sql_string(operator_reason)
    return f"""-- Explicit cutover: {new.dataset_key} {old.version} ({old.execution_model}) -> {new.version} ({new.execution_model})
-- Requires CONTROL migration 120_release_readiness.sql.
-- This file is never auto-executed by esf. Preflight, cutover, postflight and audit run in one
-- Snowflake Scripting block so any statement error is recorded in CONTROL.RELEASE_RUN.
EXECUTE IMMEDIATE $$
DECLARE
    V_RELEASE_ID VARCHAR DEFAULT UUID_STRING();
    V_PHASE VARCHAR DEFAULT 'PREFLIGHT';
    V_READINESS_STATUS VARCHAR;
    V_READINESS_REASON VARCHAR;
    V_CURRENT_ACTIVE VARCHAR;
    V_CURRENT_CANDIDATE VARCHAR;
    V_ACTIVE_STATUS_COUNT NUMBER DEFAULT 0;
    V_TARGET_ACTIVE_COUNT NUMBER DEFAULT 0;
    V_OLD_RETIRED_COUNT NUMBER DEFAULT 0;
    V_PUBLISHED_MATCH_COUNT NUMBER DEFAULT 0;
    E_RELEASE_BLOCKED EXCEPTION (-20040, 'Release preflight is BLOCKED.');
    E_REVIEW_REQUIRED EXCEPTION (-20041, 'Release preflight requires explicit reviewed-evidence acceptance.');
    E_POSTFLIGHT_FAILED EXCEPTION (-20042, 'Release postflight failed.');
BEGIN
    INSERT INTO CONTROL.RELEASE_RUN (
        RELEASE_ID, DATASET_ID, ACTION, FROM_VERSION, TO_VERSION, STATUS,
        ALLOW_REVIEW_REQUIRED, OPERATOR_REASON, STARTED_AT,
        OPERATOR_USER, OPERATOR_ROLE, WAREHOUSE_NAME
    ) VALUES (
        :V_RELEASE_ID, '{new.dataset_key}', 'ACTIVATE', '{old.version}', '{new.version}', 'STARTED',
        {allow}, {reason}, CURRENT_TIMESTAMP(),
        CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()
    );

    -- PREFLIGHT: hard invariants, candidate runtime evidence, DQ and comparison evidence.
    SELECT READINESS_STATUS, READINESS_REASON
      INTO :V_READINESS_STATUS, :V_READINESS_REASON
    FROM CONTROL.RELEASE_READINESS_V
    WHERE DATASET_ID = '{new.dataset_key}';

    UPDATE CONTROL.RELEASE_RUN
    SET PREFLIGHT_AT = CURRENT_TIMESTAMP(),
        PREFLIGHT_STATUS = :V_READINESS_STATUS,
        PREFLIGHT_REASON = :V_READINESS_REASON
    WHERE RELEASE_ID = :V_RELEASE_ID;

    IF (V_READINESS_STATUS = 'BLOCKED') THEN
        RAISE E_RELEASE_BLOCKED;
    END IF;
    IF (V_READINESS_STATUS = 'REVIEW_REQUIRED' AND NOT {allow}) THEN
        RAISE E_REVIEW_REQUIRED;
    END IF;

    V_CURRENT_ACTIVE := (
        SELECT ACTIVE_VERSION FROM CONTROL.DATASET WHERE DATASET_ID = '{new.dataset_key}'
    );
    V_CURRENT_CANDIDATE := (
        SELECT CANDIDATE_VERSION FROM CONTROL.DATASET WHERE DATASET_ID = '{new.dataset_key}'
    );
    IF (V_CURRENT_ACTIVE <> '{old.version}' OR V_CURRENT_CANDIDATE <> '{new.version}') THEN
        RAISE E_RELEASE_BLOCKED;
    END IF;

    V_PHASE := 'CUTOVER';

{prepare_new}
{publish_sql}

    -- Switch version statuses together so two ACTIVE rows are not committed by separate updates.
    UPDATE CONTROL.DATASET_VERSION
    SET STATUS = CASE
            WHEN VERSION = '{new.version}' THEN 'ACTIVE'
            WHEN VERSION = '{old.version}' THEN 'RETIRED'
            ELSE STATUS
        END,
        ACTIVATED_AT = IFF(VERSION = '{new.version}', CURRENT_TIMESTAMP(), ACTIVATED_AT),
        RETIRED_AT = CASE
            WHEN VERSION = '{new.version}' THEN NULL
            WHEN VERSION = '{old.version}' THEN CURRENT_TIMESTAMP()
            ELSE RETIRED_AT
        END,
        UPDATED_AT = CURRENT_TIMESTAMP()
    WHERE DATASET_ID = '{new.dataset_key}'
      AND VERSION IN ('{old.version}', '{new.version}');

    UPDATE CONTROL.DATASET
    SET ACTIVE_VERSION = '{new.version}',
        CANDIDATE_VERSION = NULL,
        UPDATED_AT = CURRENT_TIMESTAMP()
    WHERE DATASET_ID = '{new.dataset_key}'
      AND ACTIVE_VERSION = '{old.version}'
      AND CANDIDATE_VERSION = '{new.version}';

    UPDATE CONTROL.RELEASE_RUN
    SET CUTOVER_AT = CURRENT_TIMESTAMP()
    WHERE RELEASE_ID = :V_RELEASE_ID;

    -- Retire old processing last among cutover mutations.
{retire_old}

    V_PHASE := 'POSTFLIGHT';

    SELECT ACTIVE_VERSION, CANDIDATE_VERSION
      INTO :V_CURRENT_ACTIVE, :V_CURRENT_CANDIDATE
    FROM CONTROL.DATASET
    WHERE DATASET_ID = '{new.dataset_key}';

    V_ACTIVE_STATUS_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{new.dataset_key}'
          AND UPPER(COALESCE(STATUS, '')) = 'ACTIVE'
    );
    V_TARGET_ACTIVE_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{new.dataset_key}'
          AND VERSION = '{new.version}'
          AND UPPER(COALESCE(STATUS, '')) = 'ACTIVE'
    );
    V_OLD_RETIRED_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{new.dataset_key}'
          AND VERSION = '{old.version}'
          AND UPPER(COALESCE(STATUS, '')) = 'RETIRED'
    );
    V_PUBLISHED_MATCH_COUNT := (
        {published_match_query}
    );

    IF (
        V_CURRENT_ACTIVE <> '{new.version}'
        OR V_CURRENT_CANDIDATE IS NOT NULL
        OR V_ACTIVE_STATUS_COUNT <> 1
        OR V_TARGET_ACTIVE_COUNT <> 1
        OR V_OLD_RETIRED_COUNT <> 1
        OR V_PUBLISHED_MATCH_COUNT <> {expected_views}
    ) THEN
        RAISE E_POSTFLIGHT_FAILED;
    END IF;

    UPDATE CONTROL.RELEASE_RUN
    SET STATUS = 'SUCCEEDED',
        POSTFLIGHT_AT = CURRENT_TIMESTAMP(),
        COMPLETED_AT = CURRENT_TIMESTAMP(),
        POSTFLIGHT_STATUS = 'PASS',
        POSTFLIGHT_REASON = 'active/candidate pointers, version statuses and published view dependency verified'
    WHERE RELEASE_ID = :V_RELEASE_ID;

    RETURN OBJECT_CONSTRUCT(
        'release_id', V_RELEASE_ID,
        'status', 'SUCCEEDED',
        'dataset_id', '{new.dataset_key}',
        'active_version', '{new.version}'
    );
EXCEPTION
    WHEN OTHER THEN
        UPDATE CONTROL.RELEASE_RUN
        SET STATUS = 'FAILED',
            FAILED_PHASE = :V_PHASE,
            COMPLETED_AT = CURRENT_TIMESTAMP(),
            ERROR_CODE = TO_VARCHAR(SQLCODE),
            ERROR_MESSAGE = SQLERRM
        WHERE RELEASE_ID = :V_RELEASE_ID;
        RAISE;
END;
$$;
"""


def _render_rollback_script(
    pattern: str,
    active: PipelineNames,
    target: PipelineNames,
    *,
    operator_reason: str | None,
) -> str:
    prepare_target = _prepare_runtime(target)
    publish_sql = _published_replacement(pattern, target)
    retire_active = _retire_runtime(active)
    expected_views, published_match_query = _published_match_query(pattern, target)
    reason = _sql_string(operator_reason)
    return f"""-- Explicit rollback: {active.dataset_key} {active.version} ({active.execution_model}) -> {target.version} ({target.execution_model})
-- Requires CONTROL migration 120_release_readiness.sql.
-- Rollback is fail-closed if another candidate has been registered since the cutover.
EXECUTE IMMEDIATE $$
DECLARE
    V_RELEASE_ID VARCHAR DEFAULT UUID_STRING();
    V_PHASE VARCHAR DEFAULT 'PREFLIGHT';
    V_CURRENT_ACTIVE VARCHAR;
    V_CURRENT_CANDIDATE VARCHAR;
    V_ACTIVE_STATUS_COUNT NUMBER DEFAULT 0;
    V_TARGET_STATUS VARCHAR;
    V_TARGET_ACTIVE_COUNT NUMBER DEFAULT 0;
    V_OLD_RETIRED_COUNT NUMBER DEFAULT 0;
    V_PUBLISHED_MATCH_COUNT NUMBER DEFAULT 0;
    E_ROLLBACK_BLOCKED EXCEPTION (-20043, 'Rollback preflight is BLOCKED.');
    E_POSTFLIGHT_FAILED EXCEPTION (-20044, 'Rollback postflight failed.');
BEGIN
    INSERT INTO CONTROL.RELEASE_RUN (
        RELEASE_ID, DATASET_ID, ACTION, FROM_VERSION, TO_VERSION, STATUS,
        ALLOW_REVIEW_REQUIRED, OPERATOR_REASON, STARTED_AT,
        OPERATOR_USER, OPERATOR_ROLE, WAREHOUSE_NAME
    ) VALUES (
        :V_RELEASE_ID, '{active.dataset_key}', 'ROLLBACK', '{active.version}', '{target.version}', 'STARTED',
        FALSE, {reason}, CURRENT_TIMESTAMP(),
        CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()
    );

    SELECT ACTIVE_VERSION, CANDIDATE_VERSION
      INTO :V_CURRENT_ACTIVE, :V_CURRENT_CANDIDATE
    FROM CONTROL.DATASET
    WHERE DATASET_ID = '{active.dataset_key}';

    V_ACTIVE_STATUS_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{active.dataset_key}'
          AND UPPER(COALESCE(STATUS, '')) = 'ACTIVE'
    );
    V_TARGET_STATUS := (
        SELECT MAX(STATUS)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{active.dataset_key}'
          AND VERSION = '{target.version}'
    );

    IF (
        V_CURRENT_ACTIVE <> '{active.version}'
        OR V_CURRENT_CANDIDATE IS NOT NULL
        OR V_ACTIVE_STATUS_COUNT <> 1
        OR UPPER(COALESCE(V_TARGET_STATUS, '')) <> 'RETIRED'
    ) THEN
        UPDATE CONTROL.RELEASE_RUN
        SET PREFLIGHT_AT = CURRENT_TIMESTAMP(),
            PREFLIGHT_STATUS = 'BLOCKED',
            PREFLIGHT_REASON = 'rollback requires expected active version, no new candidate, one ACTIVE row and RETIRED target'
        WHERE RELEASE_ID = :V_RELEASE_ID;
        RAISE E_ROLLBACK_BLOCKED;
    END IF;

    UPDATE CONTROL.RELEASE_RUN
    SET PREFLIGHT_AT = CURRENT_TIMESTAMP(),
        PREFLIGHT_STATUS = 'READY',
        PREFLIGHT_REASON = 'rollback target is the retired prior implementation and no new candidate is registered'
    WHERE RELEASE_ID = :V_RELEASE_ID;

    V_PHASE := 'CUTOVER';

{prepare_target}
{publish_sql}

    UPDATE CONTROL.DATASET_VERSION
    SET STATUS = CASE
            WHEN VERSION = '{target.version}' THEN 'ACTIVE'
            WHEN VERSION = '{active.version}' THEN 'RETIRED'
            ELSE STATUS
        END,
        ACTIVATED_AT = IFF(VERSION = '{target.version}', CURRENT_TIMESTAMP(), ACTIVATED_AT),
        RETIRED_AT = CASE
            WHEN VERSION = '{target.version}' THEN NULL
            WHEN VERSION = '{active.version}' THEN CURRENT_TIMESTAMP()
            ELSE RETIRED_AT
        END,
        UPDATED_AT = CURRENT_TIMESTAMP()
    WHERE DATASET_ID = '{active.dataset_key}'
      AND VERSION IN ('{active.version}', '{target.version}');

    UPDATE CONTROL.DATASET
    SET ACTIVE_VERSION = '{target.version}',
        CANDIDATE_VERSION = NULL,
        UPDATED_AT = CURRENT_TIMESTAMP()
    WHERE DATASET_ID = '{active.dataset_key}'
      AND ACTIVE_VERSION = '{active.version}'
      AND CANDIDATE_VERSION IS NULL;

    UPDATE CONTROL.RELEASE_RUN
    SET CUTOVER_AT = CURRENT_TIMESTAMP()
    WHERE RELEASE_ID = :V_RELEASE_ID;

{retire_active}

    V_PHASE := 'POSTFLIGHT';

    SELECT ACTIVE_VERSION, CANDIDATE_VERSION
      INTO :V_CURRENT_ACTIVE, :V_CURRENT_CANDIDATE
    FROM CONTROL.DATASET
    WHERE DATASET_ID = '{active.dataset_key}';

    V_ACTIVE_STATUS_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{active.dataset_key}'
          AND UPPER(COALESCE(STATUS, '')) = 'ACTIVE'
    );
    V_TARGET_ACTIVE_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{active.dataset_key}'
          AND VERSION = '{target.version}'
          AND UPPER(COALESCE(STATUS, '')) = 'ACTIVE'
    );
    V_OLD_RETIRED_COUNT := (
        SELECT COUNT(*)
        FROM CONTROL.DATASET_VERSION
        WHERE DATASET_ID = '{active.dataset_key}'
          AND VERSION = '{active.version}'
          AND UPPER(COALESCE(STATUS, '')) = 'RETIRED'
    );
    V_PUBLISHED_MATCH_COUNT := (
        {published_match_query}
    );

    IF (
        V_CURRENT_ACTIVE <> '{target.version}'
        OR V_CURRENT_CANDIDATE IS NOT NULL
        OR V_ACTIVE_STATUS_COUNT <> 1
        OR V_TARGET_ACTIVE_COUNT <> 1
        OR V_OLD_RETIRED_COUNT <> 1
        OR V_PUBLISHED_MATCH_COUNT <> {expected_views}
    ) THEN
        RAISE E_POSTFLIGHT_FAILED;
    END IF;

    UPDATE CONTROL.RELEASE_RUN
    SET STATUS = 'SUCCEEDED',
        POSTFLIGHT_AT = CURRENT_TIMESTAMP(),
        COMPLETED_AT = CURRENT_TIMESTAMP(),
        POSTFLIGHT_STATUS = 'PASS',
        POSTFLIGHT_REASON = 'rollback pointers, version statuses and published view dependency verified'
    WHERE RELEASE_ID = :V_RELEASE_ID;

    RETURN OBJECT_CONSTRUCT(
        'release_id', V_RELEASE_ID,
        'status', 'SUCCEEDED',
        'dataset_id', '{active.dataset_key}',
        'active_version', '{target.version}'
    );
EXCEPTION
    WHEN OTHER THEN
        UPDATE CONTROL.RELEASE_RUN
        SET STATUS = 'FAILED',
            FAILED_PHASE = :V_PHASE,
            COMPLETED_AT = CURRENT_TIMESTAMP(),
            ERROR_CODE = TO_VARCHAR(SQLCODE),
            ERROR_MESSAGE = SQLERRM
        WHERE RELEASE_ID = :V_RELEASE_ID;
        RAISE;
END;
$$;
"""


def render_release_sql(
    pattern: str,
    names_from: PipelineNames,
    names_to: PipelineNames,
    *,
    allow_review_required: bool = False,
    operator_reason: str | None = None,
) -> tuple[str, str]:
    if pattern == "custom":
        raise ValueError("custom pipelines require domain-authored activation and rollback SQL")
    if allow_review_required and not operator_reason:
        raise ValueError("operator_reason is required when allowing REVIEW_REQUIRED release evidence")

    activate = _render_activate_script(
        pattern,
        names_from,
        names_to,
        allow_review_required=allow_review_required,
        operator_reason=operator_reason,
    )
    rollback = _render_rollback_script(
        pattern,
        names_to,
        names_from,
        operator_reason=operator_reason,
    )
    return activate, rollback
