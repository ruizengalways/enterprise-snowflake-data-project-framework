-- Executable Snowflake behavior oracle. dbt singular tests pass when this query
-- returns zero rows. The same fixture is rendered offline by Framework CI; once
-- a Snowflake integration target is available, `dbt test --select scd2_behavior`
-- executes the real framework SQL without a custom test runner.

{{ smoke_scd2_behavior_sql() }}
