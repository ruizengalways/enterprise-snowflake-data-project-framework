from __future__ import annotations

from .pipeline_model import PipelineNames


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


def _retire_runtime(names: PipelineNames) -> str:
    if names.execution_model == "stream_task" and names.task:
        return f"ALTER TASK {names.task} SUSPEND;"
    if names.execution_model == "dynamic_table" and names.dynamic_table:
        return f"ALTER DYNAMIC TABLE {names.dynamic_table} SUSPEND;"
    if names.execution_model == "batch_sql":
        return "-- Batch SQL implementation has no scheduler to suspend."
    return "-- Custom implementation: retire the domain-owned runtime explicitly."


def _target_readiness_note(names: PipelineNames, *, rollback: bool) -> str:
    action = "rollback target" if rollback else "candidate"
    if names.execution_model == "stream_task":
        return (
            f"-- The {action} Stream/Task runtime must already be caught up and in the reviewed operational state.\n"
            "-- This cutover does not RESUME or execute it after preflight because that would create new runtime evidence\n"
            "-- after DQ/comparison had already been accepted.\n"
        )
    if names.execution_model == "dynamic_table":
        return (
            f"-- The {action} Dynamic Table must already be refreshed/caught up before preflight.\n"
            "-- This cutover deliberately does not issue ALTER DYNAMIC TABLE ... REFRESH after validation.\n"
        )
    if names.execution_model == "batch_sql":
        return (
            f"-- The {action} batch implementation must already have completed its reviewed apply/validate path.\n"
            "-- External scheduler state remains an operator-owned release concern.\n"
        )
    return f"-- The {action} custom runtime must already satisfy its domain-owned readiness procedure.\n"


def _view_definition_reference_predicate(relation: str) -> str:
    pattern = relation.upper().replace(".", "[.]")
    return (
        "REGEXP_INSTR(UPPER(COALESCE(VIEW_DEFINITION, '')), "
        f"'(^|[^A-Z0-9_]){pattern}([^A-Z0-9_]|$)') > 0"
    )


def _published_match_query(pattern: str, names: PipelineNames) -> tuple[int, str]:
    if pattern == "scd2":
        assert names.history_relation and names.published_history and names.published_current
        history_view = names.published_history.split(".", 1)[1]
        current_view = names.published_current.split(".", 1)[1]
        reference_match = _view_definition_reference_predicate(names.history_relation)
        return 2, f"""SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.VIEWS
        WHERE TABLE_SCHEMA = 'SILVER'
          AND (
                (TABLE_NAME = '{history_view}' AND {reference_match})
             OR (TABLE_NAME = '{current_view}' AND {reference_match})
          )"""
    assert names.physical_relation and names.published_relation
    published_view = names.published_relation.split(".", 1)[1]
    reference_match = _view_definition_reference_predicate(names.physical_relation)
    return 1, f"""SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.VIEWS
        WHERE TABLE_SCHEMA = 'SILVER'
          AND TABLE_NAME = '{published_view}'
          AND {reference_match}"""


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
    readiness_note = _target_readiness_note(new, rollback=False)
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

    SELECT ACTIVE_VERSION, CANDIDATE_VERSION
      INTO :V_CURRENT_ACTIVE, :V_CURRENT_CANDIDATE
    FROM CONTROL.DATASET
    WHERE DATASET_ID = '{new.dataset_key}';
    IF (V_CURRENT_ACTIVE <> '{old.version}' OR V_CURRENT_CANDIDATE <> '{new.version}') THEN
        RAISE E_RELEASE_BLOCKED;
    END IF;

    V_PHASE := 'CUTOVER';

{readiness_note}
{publish_sql}

    -- Switch both version statuses in one statement so two ACTIVE rows are not created by
    -- separate old/new status mutations.
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

    -- Retire old processing last among cutover mutations. A publication/control failure before
    -- this point leaves the old processing path available for state inspection and correction.
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
    readiness_note = _target_readiness_note(target, rollback=True)
    publish_sql = _published_replacement(pattern, target)
    retire_active = _retire_runtime(active)
    expected_views, published_match_query = _published_match_query(pattern, target)
    reason = _sql_string(operator_reason)
    return f"""-- Explicit rollback: {active.dataset_key} {active.version} ({active.execution_model}) -> {target.version} ({target.execution_model})
-- Requires CONTROL migration 120_release_readiness.sql.
-- Rollback is fail-closed if another candidate has been registered since the cutover.
-- The retired target must be caught up and revalidated before this script is run.
EXECUTE IMMEDIATE $$
DECLARE
    V_RELEASE_ID VARCHAR DEFAULT UUID_STRING();
    V_PHASE VARCHAR DEFAULT 'PREFLIGHT';
    V_CURRENT_ACTIVE VARCHAR;
    V_CURRENT_CANDIDATE VARCHAR;
    V_ACTIVE_STATUS_COUNT NUMBER DEFAULT 0;
    V_TARGET_STATUS VARCHAR;
    V_ACTIVE_RUNTIME_EVIDENCE_AT TIMESTAMP_LTZ;
    V_ACTIVE_DATA_MAX_AT TIMESTAMP_LTZ;
    V_TARGET_RUNTIME_STATUS VARCHAR;
    V_TARGET_RUNTIME_EVIDENCE_AT TIMESTAMP_LTZ;
    V_TARGET_DATA_MAX_AT TIMESTAMP_LTZ;
    V_TARGET_DQ_STATUS VARCHAR;
    V_TARGET_DQ_CHECKED_AT TIMESTAMP_LTZ;
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
    V_ACTIVE_RUNTIME_EVIDENCE_AT := (
        SELECT MAX(RUNTIME_EVIDENCE_AT)
        FROM CONTROL.VERSION_RUNTIME_STATUS_V
        WHERE DATASET_ID = '{active.dataset_key}'
          AND VERSION = '{active.version}'
    );
    V_ACTIVE_DATA_MAX_AT := (
        SELECT MAX(DATA_MAX_AT)
        FROM CONTROL.VERSION_RUNTIME_STATUS_V
        WHERE DATASET_ID = '{active.dataset_key}'
          AND VERSION = '{active.version}'
    );
    V_TARGET_RUNTIME_STATUS := (
        SELECT MAX(RUNTIME_STATUS)
        FROM CONTROL.VERSION_RUNTIME_STATUS_V
        WHERE DATASET_ID = '{active.dataset_key}'
          AND VERSION = '{target.version}'
    );
    V_TARGET_RUNTIME_EVIDENCE_AT := (
        SELECT MAX(RUNTIME_EVIDENCE_AT)
        FROM CONTROL.VERSION_RUNTIME_STATUS_V
        WHERE DATASET_ID = '{active.dataset_key}'
          AND VERSION = '{target.version}'
    );
    V_TARGET_DATA_MAX_AT := (
        SELECT MAX(DATA_MAX_AT)
        FROM CONTROL.VERSION_RUNTIME_STATUS_V
        WHERE DATASET_ID = '{active.dataset_key}'
          AND VERSION = '{target.version}'
    );
    V_TARGET_DQ_STATUS := (
        SELECT MAX(DQ_STATUS)
        FROM CONTROL.DQ_LATEST_RUN_V
        WHERE DATASET_ID = '{active.dataset_key}'
          AND VERSION = '{target.version}'
    );
    V_TARGET_DQ_CHECKED_AT := (
        SELECT MAX(CHECKED_AT)
        FROM CONTROL.DQ_LATEST_RUN_V
        WHERE DATASET_ID = '{active.dataset_key}'
          AND VERSION = '{target.version}'
    );

    IF (
        V_CURRENT_ACTIVE <> '{active.version}'
        OR V_CURRENT_CANDIDATE IS NOT NULL
        OR V_ACTIVE_STATUS_COUNT <> 1
        OR UPPER(COALESCE(V_TARGET_STATUS, '')) <> 'RETIRED'
        OR V_ACTIVE_RUNTIME_EVIDENCE_AT IS NULL
        OR UPPER(COALESCE(V_TARGET_RUNTIME_STATUS, '')) <> 'SUCCESS'
        OR V_TARGET_RUNTIME_EVIDENCE_AT IS NULL
        OR UPPER(COALESCE(V_TARGET_DQ_STATUS, '')) <> 'PASS'
        OR V_TARGET_DQ_CHECKED_AT IS NULL
        OR V_TARGET_DQ_CHECKED_AT < V_TARGET_RUNTIME_EVIDENCE_AT
        OR (
            V_ACTIVE_DATA_MAX_AT IS NOT NULL
            AND (V_TARGET_DATA_MAX_AT IS NULL OR V_TARGET_DATA_MAX_AT < V_ACTIVE_DATA_MAX_AT)
        )
        OR (
            V_ACTIVE_DATA_MAX_AT IS NULL
            AND V_TARGET_RUNTIME_EVIDENCE_AT < V_ACTIVE_RUNTIME_EVIDENCE_AT
        )
    ) THEN
        UPDATE CONTROL.RELEASE_RUN
        SET PREFLIGHT_AT = CURRENT_TIMESTAMP(),
            PREFLIGHT_STATUS = 'BLOCKED',
            PREFLIGHT_REASON = 'rollback requires expected pointers/statuses plus caught-up SUCCESS target runtime and fresh PASS target DQ'
        WHERE RELEASE_ID = :V_RELEASE_ID;
        RAISE E_ROLLBACK_BLOCKED;
    END IF;

    UPDATE CONTROL.RELEASE_RUN
    SET PREFLIGHT_AT = CURRENT_TIMESTAMP(),
        PREFLIGHT_STATUS = 'READY',
        PREFLIGHT_REASON = 'rollback target is retired, caught up, runtime SUCCESS and DQ PASS after target runtime evidence'
    WHERE RELEASE_ID = :V_RELEASE_ID;

    V_PHASE := 'CUTOVER';

{readiness_note}
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
