-- Example only. Copy into the source-specific ingestion implementation and replace values.
-- This records operational evidence; it does not implement ingestion or connector state.

SET ESF_RUN_ID = UUID_STRING();

CALL CONTROL.BEGIN_INGESTION_RUN(
    $ESF_RUN_ID,
    'fleet_mssql.customer',
    'fleet_mssql',
    'OPENFLOW',
    'replace-with-native-flow-or-batch-id',
    TO_TIMESTAMP_LTZ('2026-09-10 09:00:00 +10:00'),
    TO_TIMESTAMP_LTZ('2026-09-10 09:05:00 +10:00')
);

-- Run or wait for the source-specific Bronze ingestion here.

CALL CONTROL.COMPLETE_INGESTION_RUN(
    $ESF_RUN_ID,
    CURRENT_TIMESTAMP(),
    12500
);

-- Failure path instead of COMPLETE:
-- CALL CONTROL.FAIL_INGESTION_RUN(
--     $ESF_RUN_ID,
--     'CONNECTOR_ERROR',
--     'replace with the source-specific error message'
-- );
