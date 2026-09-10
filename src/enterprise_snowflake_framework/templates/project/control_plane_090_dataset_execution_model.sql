-- Add version-level execution technology without changing logical dataset semantics.
-- This is a new apply-once migration. Do not back-edit 001..080.

ALTER TABLE CONTROL.DATASET_VERSION ADD COLUMN EXECUTION_MODEL VARCHAR;
ALTER TABLE CONTROL.DATASET_VERSION ADD COLUMN PRIMARY_RUNTIME_OBJECT VARCHAR;

-- Existing versions were generated before execution_model was explicit. Preserve their
-- historical implementation meaning rather than guessing a new technology.
UPDATE CONTROL.DATASET_VERSION
SET EXECUTION_MODEL = CASE
        WHEN TASK_OBJECT IS NOT NULL THEN 'stream_task'
        WHEN APPLY_OBJECT IS NOT NULL THEN 'batch_sql'
        ELSE 'custom'
    END,
    PRIMARY_RUNTIME_OBJECT = COALESCE(TASK_OBJECT, APPLY_OBJECT, CURRENT_RELATION, HISTORY_RELATION),
    UPDATED_AT = CURRENT_TIMESTAMP()
WHERE EXECUTION_MODEL IS NULL;
