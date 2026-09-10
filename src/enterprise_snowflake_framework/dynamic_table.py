from __future__ import annotations

from typing import Any

from .pipeline_model import PipelineNames, _csv, column_names, ordered_columns


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _tombstone_predicate(contract: dict[str, Any], alias: str = "B") -> str:
    changes = contract.get("change_semantics", {})
    if changes.get("delete_semantics") != "tombstone" or not changes.get("operation_column"):
        return "FALSE"
    operation = str(changes["operation_column"]).upper()
    values = ", ".join(
        _sql_string(str(value).upper()) for value in changes.get("delete_values", [])
    )
    if not values:
        return "FALSE"
    return f"UPPER(COALESCE(TO_VARCHAR({alias}.{operation}), '')) IN ({values})"


def render_dynamic_table_sql(
    pattern: str,
    names: PipelineNames,
    contract: dict[str, Any],
    *,
    target_lag: str,
    warehouse: str,
    refresh_mode: str,
) -> str:
    if pattern not in {"scd1", "full_refresh"}:
        raise ValueError("Dynamic Table rendering currently supports scd1 and full_refresh only")
    if not names.physical_relation:
        raise ValueError("Dynamic Table execution requires a physical Silver relation")
    columns = column_names(contract)
    source_loaded = "INGESTED_AT" if "INGESTED_AT" in columns else (
        str(contract.get("source_timestamp", "")).upper() or columns[-1]
    )
    header = f"""-- {names.dataset_key} {names.version}: declarative Snowflake Dynamic Table implementation.
-- Semantic pattern remains {pattern}; execution technology is version-specific.
-- TARGET_LAG is an execution staleness target, not the logical dataset SLA.
-- CREATE is fail-closed because this is a new version-owned runtime object.
CREATE DYNAMIC TABLE {names.physical_relation}
    TARGET_LAG = {_sql_string(target_lag)}
    WAREHOUSE = {warehouse}
    REFRESH_MODE = {refresh_mode.upper()}
    INITIALIZE = ON_CREATE
AS
"""
    if pattern == "full_refresh":
        return header + f"""SELECT
    {_csv(columns, 'B')},
    B.{source_loaded} AS ESF_LOADED_AT
FROM {names.bronze_relation} B;
"""

    business_key = [str(value).upper() for value in contract.get("business_key", [])]
    ordering = ordered_columns(contract)
    if not business_key or not ordering:
        raise ValueError("scd1 Dynamic Table requires business_key and ordering evidence")
    order_desc = ", ".join(f"B.{name} DESC" for name in ordering)
    delete_expr = _tombstone_predicate(contract, "B")
    return header + f"""WITH RANKED AS (
    SELECT
        {_csv(columns, 'B')},
        B.{source_loaded} AS ESF_LOADED_AT,
        {delete_expr} AS ESF_IS_DELETE,
        ROW_NUMBER() OVER (
            PARTITION BY {_csv(business_key, 'B')}
            ORDER BY {order_desc}
        ) AS ESF_ROW_NUMBER
    FROM {names.bronze_relation} B
)
SELECT
    {_csv(columns)},
    ESF_LOADED_AT
FROM RANKED
WHERE ESF_ROW_NUMBER = 1
  AND NOT ESF_IS_DELETE;
"""


def _dq_statement(names: PipelineNames, check_id: str, query: str, description: str) -> str:
    description = description.replace("'", "''")
    return f"""INSERT INTO CONTROL.DQ_RESULT (
    RESULT_ID, RUN_ID, DATASET_ID, VERSION, CHECK_ID, CHECK_SEVERITY,
    STATUS, VIOLATION_COUNT, DETAILS, QUERY_ID, CHECKED_AT
)
WITH CHECK_RESULT AS (
    SELECT ({query}) AS VIOLATIONS
)
SELECT
    UUID_STRING(), UUID_STRING(), '{names.dataset_key}', '{names.version}', '{check_id}', 'ERROR',
    IFF(VIOLATIONS = 0, 'PASS', 'FAIL'), VIOLATIONS,
    OBJECT_CONSTRUCT('description', '{description}', 'execution_model', 'dynamic_table'),
    LAST_QUERY_ID(), CURRENT_TIMESTAMP()
FROM CHECK_RESULT;
"""


def render_dynamic_table_validation_sql(
    pattern: str, names: PipelineNames, contract: dict[str, Any]
) -> str:
    if not names.physical_relation:
        raise ValueError("Dynamic Table validation requires a physical Silver relation")
    business_key = [str(value).upper() for value in contract.get("business_key", [])]
    if not business_key:
        raise ValueError("Dynamic Table validation requires a business key")
    keys = _csv(business_key)
    null_predicate = " OR ".join(f"{name} IS NULL" for name in business_key)
    checks = [
        _dq_statement(
            names,
            "duplicate_business_key",
            f"SELECT COUNT(*) FROM (SELECT {keys} FROM {names.physical_relation} GROUP BY {keys} HAVING COUNT(*) > 1)",
            "Declarative current-state output must contain at most one row per business key.",
        ),
        _dq_statement(
            names,
            "null_business_key",
            f"SELECT COUNT(*) FROM {names.physical_relation} WHERE {null_predicate}",
            "Business-key columns must not be NULL in Silver output.",
        ),
    ]
    return (
        "-- Explicit dataset-local DQ evidence for a Dynamic Table implementation.\n"
        "-- No fake validation procedure or Task is generated. Run this after refresh when evidence is required.\n\n"
        + "\n".join(checks)
    )
