from __future__ import annotations

from .pipeline_model import PipelineNames


def render_policy_sql(names: PipelineNames, *, candidate: bool) -> str:
    if candidate:
        return (
            f"-- {names.dataset_key} {names.version}: SLA belongs to the logical dataset, not to a candidate version.\n"
            "-- Do not duplicate logical-dataset SLA policy here.\n"
        )
    return f"""-- Optional logical-dataset SLA policy starter for {names.dataset_key}.
-- No threshold is guessed by the framework. Keep this file as documentation until the
-- domain has agreed an SLA, or replace the commented example with explicit committed SQL.
-- You can also generate a reviewable policy revision under operations/sla with `esf sla-sql`.

-- Example: continuous end-to-end freshness <= 10 minutes.
-- MERGE INTO CONTROL.SLA_POLICY P
-- USING (
--     SELECT
--         '{names.dataset_key}' AS DATASET_ID,
--         'END_TO_END' AS STAGE,
--         'CONTINUOUS' AS CADENCE_TYPE,
--         NULL AS MAX_LATENCY_SECONDS,
--         600 AS MAX_FRESHNESS_SECONDS,
--         NULL AS EXPECTED_INTERVAL_SECONDS,
--         NULL AS DEADLINE_LOCAL_TIME,
--         NULL AS TIMEZONE,
--         TRUE AS ENABLED
-- ) S
-- ON P.DATASET_ID = S.DATASET_ID AND P.STAGE = S.STAGE
-- WHEN MATCHED THEN UPDATE SET
--     CADENCE_TYPE = S.CADENCE_TYPE,
--     MAX_LATENCY_SECONDS = S.MAX_LATENCY_SECONDS,
--     MAX_FRESHNESS_SECONDS = S.MAX_FRESHNESS_SECONDS,
--     EXPECTED_INTERVAL_SECONDS = S.EXPECTED_INTERVAL_SECONDS,
--     DEADLINE_LOCAL_TIME = S.DEADLINE_LOCAL_TIME,
--     TIMEZONE = S.TIMEZONE,
--     ENABLED = S.ENABLED,
--     UPDATED_AT = CURRENT_TIMESTAMP()
-- WHEN NOT MATCHED THEN INSERT (
--     DATASET_ID, STAGE, CADENCE_TYPE,
--     MAX_LATENCY_SECONDS, MAX_FRESHNESS_SECONDS, EXPECTED_INTERVAL_SECONDS,
--     DEADLINE_LOCAL_TIME, TIMEZONE, ENABLED
-- ) VALUES (
--     S.DATASET_ID, S.STAGE, S.CADENCE_TYPE,
--     S.MAX_LATENCY_SECONDS, S.MAX_FRESHNESS_SECONDS, S.EXPECTED_INTERVAL_SECONDS,
--     S.DEADLINE_LOCAL_TIME, S.TIMEZONE, S.ENABLED
-- );
"""
