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

    {{ log('---LATEST---\n' ~ latest_sql ~ '\n---SNAPSHOT_DIFF---\n' ~ diff_sql, info=true) }}
    {{ return('capture SQL rendered') }}
{%- endmacro %}
