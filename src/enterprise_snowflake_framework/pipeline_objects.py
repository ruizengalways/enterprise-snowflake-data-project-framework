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


def render_validate_sql(pattern: str, names: PipelineNames, contract: dict[str, Any]) -> str:
    business_key = [str(value).upper() for value in contract.get("business_key", [])]
    if pattern == "custom":
        return (
            f"-- {names.dataset_key} {names.version}: custom validation.\n"
            "-- Add domain-owned validation queries here.\n"
        )
    if pattern == "scd2":
        assert names.history_relation
        keys = _csv(business_key)
        return f"""-- Non-empty results require investigation.

-- At most one active row per business key.
SELECT {keys}, COUNT(*) AS ACTIVE_ROWS
FROM {names.history_relation}
WHERE IS_ACTIVE = TRUE
GROUP BY {keys}
HAVING COUNT(*) > 1;

-- No NULL business keys.
SELECT *
FROM {names.history_relation}
WHERE {" OR ".join(name + " IS NULL" for name in business_key)};

-- No overlapping effective periods.
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
SELECT *
FROM ORDERED
WHERE PREVIOUS_VALID_TO IS NOT NULL
  AND VALID_FROM < PREVIOUS_VALID_TO;
"""
    assert names.physical_relation
    if pattern == "append":
        idempotency = [str(value).upper() for value in contract.get("idempotency_key", [])]
        keys = _csv(idempotency)
        return f"""-- Append idempotency diagnostics.
SELECT {keys}, COUNT(*) AS DUPLICATES
FROM {names.physical_relation}
GROUP BY {keys}
HAVING COUNT(*) > 1;
"""
    keys = _csv(business_key)
    return f"""-- Current-state uniqueness diagnostics.
SELECT {keys}, COUNT(*) AS ROWS_PER_KEY
FROM {names.physical_relation}
GROUP BY {keys}
HAVING COUNT(*) > 1;
"""
