{% macro smoke_capture_sql() -%}
    {%- set latest_sql -%}
{{ enterprise_snowflake_framework.esf_latest_observation(
    'OBSERVATIONS',
    ['id'],
    ['source_sequence']
) }}
    {%- endset -%}

    {%- set diff_sql -%}
{{ enterprise_snowflake_framework.esf_snapshot_diff(
    'CURRENT_SNAPSHOT',
    'PREVIOUS_SNAPSHOT',
    ['id'],
    'record_hash'
) }}
    {%- endset -%}

    {%- set stream_sql -%}
{{ enterprise_snowflake_framework.esf_append_only_stream_sql(
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT_STREAM',
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    false,
    'Consume immutable patient CDC events'
) }}
    {%- endset -%}

    {%- set task_sql -%}
{{ enterprise_snowflake_framework.esf_triggered_task_sql(
    'CI_HEALTH.PR_123_STAGING.PROCESS_PATIENT_EVENT',
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT_STREAM',
    'WH_HEALTH_CI',
    'insert into CI_HEALTH.PR_123_STAGING.PATIENT_EVENT_CONSUMED select * from CI_HEALTH.PR_123_STAGING.PATIENT_EVENT_STREAM',
    30,
    3600000,
    1,
    3,
    'Process immutable patient CDC events',
    true
) }}
    {%- endset -%}

    {{ log(
        '---LATEST---\n' ~ latest_sql
        ~ '\n---SNAPSHOT_DIFF---\n' ~ diff_sql
        ~ '\n---APPEND_ONLY_STREAM---\n' ~ stream_sql
        ~ '\n---TRIGGERED_TASK---\n' ~ task_sql,
        info=true
    ) }}
    {{ return('capture SQL rendered') }}
{%- endmacro %}
