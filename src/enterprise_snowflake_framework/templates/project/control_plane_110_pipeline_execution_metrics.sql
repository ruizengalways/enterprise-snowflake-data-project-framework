-- Canonical execution metrics for explicit Silver apply procedures.
-- Existing ROWS_INSERTED / ROWS_UPDATED / ROWS_DELETED columns are retained for compatibility,
-- but they are legacy fields because older generated patterns did not give them one cross-pattern meaning.
-- New generated procedures write METRICS_CONTRACT_VERSION = 1 and use the columns below instead.

ALTER TABLE CONTROL.PIPELINE_RUN ADD COLUMN IF NOT EXISTS METRICS_CONTRACT_VERSION NUMBER(38,0);
ALTER TABLE CONTROL.PIPELINE_RUN ADD COLUMN IF NOT EXISTS ROWS_AFFECTED NUMBER(38,0);
ALTER TABLE CONTROL.PIPELINE_RUN ADD COLUMN IF NOT EXISTS AFFECTED_BUSINESS_KEYS NUMBER(38,0);
ALTER TABLE CONTROL.PIPELINE_RUN ADD COLUMN IF NOT EXISTS DML_QUERY_ID VARCHAR;
ALTER TABLE CONTROL.PIPELINE_RUN ADD COLUMN IF NOT EXISTS METRICS VARIANT;

-- Stable read surface for canonical metrics. DATA_MAX_AT and PUBLISHED_AT are aliases over the
-- existing Silver timing columns so the migration does not duplicate established evidence.
CREATE VIEW CONTROL.PIPELINE_EXECUTION_METRICS_V AS
SELECT
    RUN_ID,
    DATASET_ID,
    VERSION,
    STATUS,
    STARTED_AT,
    COMPLETED_AT,
    ROWS_READ,
    ROWS_AFFECTED,
    AFFECTED_BUSINESS_KEYS,
    SILVER_DATA_MAX_AT AS DATA_MAX_AT,
    SILVER_PUBLISHED_AT AS PUBLISHED_AT,
    DML_QUERY_ID,
    TASK_NAME,
    WAREHOUSE_NAME,
    METRICS_CONTRACT_VERSION,
    METRICS,
    ERROR_CODE,
    ERROR_MESSAGE,
    CREATED_AT,
    -- Legacy fields remain visible for historical audit only. Do not compare them across patterns.
    ROWS_INSERTED AS LEGACY_ROWS_INSERTED,
    ROWS_UPDATED AS LEGACY_ROWS_UPDATED,
    ROWS_DELETED AS LEGACY_ROWS_DELETED
FROM CONTROL.PIPELINE_RUN;
