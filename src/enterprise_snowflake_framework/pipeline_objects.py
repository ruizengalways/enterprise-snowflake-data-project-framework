from __future__ import annotations

from typing import Any

from .pipeline_model import PipelineNames, _column_defs, _csv


def render_objects_sql(pattern: str, names: PipelineNames, contract: dict[str, Any]) -> str:
    defs = _column_defs(contract)
    if pattern == "custom":
        return (
            f"-- {names.dataset_key} {names.version}: custom pipeline objects.\n"
            "-- Define explicit domain-owned Snowflake objects here.\n"
        )
    if pattern == "scd2":
        assert names.events_relation and names.history_relation and names.current_relation and names.stream
        return f"""-- {names.dataset_key} {names.version}: retained SCD2 evidence and physical history.
-- Bronze must retain the source-change evidence promised by the RAW contract.

CREATE TABLE IF NOT EXISTS {names.events_relation} (
{defs},
    ESF_STREAM_ACTION VARCHAR NOT NULL,
    ESF_STREAM_ISUPDATE BOOLEAN NOT NULL,
    ESF_EVENT_HASH VARCHAR NOT NULL,
    ESF_CAPTURED_AT TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {names.history_relation} (
{defs},
    VALID_FROM TIMESTAMP_NTZ NOT NULL,
    VALID_TO TIMESTAMP_NTZ,
    IS_ACTIVE BOOLEAN NOT NULL,
    ESF_VERSION_HASH VARCHAR NOT NULL,
    ESF_BUILT_AT TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE VIEW {names.current_relation} AS
SELECT *
FROM {names.history_relation}
WHERE IS_ACTIVE = TRUE;

CREATE STREAM IF NOT EXISTS {names.stream}
    ON TABLE {names.bronze_relation}
    APPEND_ONLY = FALSE;
"""
    assert names.physical_relation
    stream_sql = ""
    if names.stream:
        stream_sql = f"""

CREATE STREAM IF NOT EXISTS {names.stream}
    ON TABLE {names.bronze_relation}
    APPEND_ONLY = FALSE;
"""
    return f"""-- {names.dataset_key} {names.version}: versioned Silver table.

CREATE TABLE IF NOT EXISTS {names.physical_relation} (
{defs},
    ESF_LOADED_AT TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);{stream_sql}"""


def _dq_insert(names: PipelineNames, check_id: str, query: str, description: str) -> str:
    escaped_description = description.replace("'", "''")
    return f"""    V_VIOLATIONS := ({query});

    INSERT INTO CONTROL.DQ_RESULT (
        RESULT_ID, RUN_ID, DATASET_ID, VERSION, CHECK_ID, CHECK_SEVERITY,
        STATUS, VIOLATION_COUNT, DETAILS, QUERY_ID, CHECKED_AT
    ) VALUES (
        UUID_STRING(), :V_RUN_ID, '{names.dataset_key}', '{names.version}', '{check_id}', 'ERROR',
        IFF(:V_VIOLATIONS = 0, 'PASS', 'FAIL'), :V_VIOLATIONS,
        OBJECT_CONSTRUCT('description', '{escaped_description}'), LAST_QUERY_ID(), CURRENT_TIMESTAMP()
    );

    V_FAILED_CHECKS := V_FAILED_CHECKS + IFF(V_VIOLATIONS > 0, 1, 0);
    V_CHECKS := V_CHECKS + 1;
"""


def _validation_procedure(names: PipelineNames, checks: list[tuple[str, str, str]]) -> str:
    rendered = "\n".join(_dq_insert(names, check_id, query, description) for check_id, query, description in checks)
    return f"""-- Dataset-local structural validation. Business DQ rules may be added here by the domain.
-- Results are normalized into CONTROL.DQ_RESULT; CONTROL does not define these checks at runtime.
CREATE OR REPLACE PROCEDURE {names.validate_procedure}()
RETURNS OBJECT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    V_RUN_ID VARCHAR DEFAULT UUID_STRING();
    V_VIOLATIONS NUMBER DEFAULT 0;
    V_CHECKS NUMBER DEFAULT 0;
    V_FAILED_CHECKS NUMBER DEFAULT 0;
BEGIN
{rendered}
    RETURN OBJECT_CONSTRUCT(
        'run_id', V_RUN_ID,
        'dataset_id', '{names.dataset_key}',
        'version', '{names.version}',
        'checks', V_CHECKS,
        'failed_checks', V_FAILED_CHECKS,
        'status', IFF(V_FAILED_CHECKS = 0, 'PASS', 'FAIL')
    );
END;
$$;
"""


def render_validate_sql(pattern: str, names: PipelineNames, contract: dict[str, Any]) -> str:
    business_key = [str(value).upper() for value in contract.get("business_key", [])]
    if pattern == "custom":
        return (
            f"-- {names.dataset_key} {names.version}: custom validation.\n"
            "-- Define explicit domain-owned checks here. When useful, record normalized evidence in "
            "CONTROL.DQ_RESULT or call CONTROL.RECORD_DQ_RESULT.\n"
        )

    null_predicate = " OR ".join(name + " IS NULL" for name in business_key)
    checks: list[tuple[str, str, str]] = []

    if pattern == "scd2":
        assert names.history_relation
        keys = _csv(business_key)
        checks.extend(
            [
                (
                    "multiple_active_rows",
                    f"""SELECT COUNT(*) FROM (
            SELECT {keys}
            FROM {names.history_relation}
            WHERE IS_ACTIVE = TRUE
            GROUP BY {keys}
            HAVING COUNT(*) > 1
        )""",
                    "At most one active history row may exist per business key.",
                ),
                (
                    "null_business_key",
                    f"SELECT COUNT(*) FROM {names.history_relation} WHERE {null_predicate}",
                    "Business-key columns must not be NULL in Silver history.",
                ),
                (
                    "overlapping_effective_periods",
                    f"""SELECT COUNT(*) FROM (
            WITH ORDERED AS (
                SELECT
                    {keys},
                    VALID_FROM,
                    VALID_TO,
                    LAG(VALID_TO) OVER (
                        PARTITION BY {keys}
                        ORDER BY VALID_FROM
                    ) AS PREVIOUS_VALID_TO
                FROM {names.history_relation}
            )
            SELECT 1
            FROM ORDERED
            WHERE PREVIOUS_VALID_TO IS NOT NULL
              AND VALID_FROM < PREVIOUS_VALID_TO
        )""",
                    "SCD2 effective periods must not overlap for a business key.",
                ),
            ]
        )
        return _validation_procedure(names, checks)

    assert names.physical_relation
    if pattern == "append":
        idempotency = [str(value).upper() for value in contract.get("idempotency_key", [])]
        keys = _csv(idempotency)
        checks.append(
            (
                "duplicate_idempotency_key",
                f"""SELECT COUNT(*) FROM (
            SELECT {keys}
            FROM {names.physical_relation}
            GROUP BY {keys}
            HAVING COUNT(*) > 1
        )""",
                "Append output must preserve one Silver row per RAW-contract idempotency key.",
            )
        )
    else:
        keys = _csv(business_key)
        checks.append(
            (
                "duplicate_business_key",
                f"""SELECT COUNT(*) FROM (
            SELECT {keys}
            FROM {names.physical_relation}
            GROUP BY {keys}
            HAVING COUNT(*) > 1
        )""",
                "Current-state output must contain at most one row per business key.",
            )
        )

    checks.append(
        (
            "null_business_key",
            f"SELECT COUNT(*) FROM {names.physical_relation} WHERE {null_predicate}",
            "Business-key columns must not be NULL in Silver output.",
        )
    )
    return _validation_procedure(names, checks)
