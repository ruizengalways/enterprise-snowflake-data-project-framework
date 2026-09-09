-- Low-latency domain health evaluation.
-- Uses serverless task compute so a one-minute health check does not wake a domain transform warehouse.
-- Snowflake creates a new task suspended; resume it only after CONTROL objects and policy are validated.

CREATE TASK IF NOT EXISTS CONTROL.EVALUATE_DOMAIN_HEALTH_TASK
    USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE = 'XSMALL'
    SCHEDULE = '1 MINUTE'
    USER_TASK_TIMEOUT_MS = 60000
    SUSPEND_TASK_AFTER_NUM_FAILURES = 3
AS
    CALL CONTROL.EVALUATE_DOMAIN_HEALTH();

-- Explicit go-live after validation:
-- ALTER TASK CONTROL.EVALUATE_DOMAIN_HEALTH_TASK RESUME;

-- Manual test before resume:
-- EXECUTE TASK CONTROL.EVALUATE_DOMAIN_HEALTH_TASK;
