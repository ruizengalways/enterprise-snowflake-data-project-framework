{% macro smoke_metadata_scd2_sql() -%}
    {%- set event_sql = enterprise_snowflake_framework.esf_scd2_history_select_for_dataset(
        'RAW_EVENT_ROWS',
        'smoke_scd2'
    ) -%}
    {%- set snapshot_sql = enterprise_snowflake_framework.esf_scd2_snapshot_apply_for_dataset_sql(
        'SNAPSHOT_HISTORY',
        'RAW_SNAPSHOT_ROWS',
        'smoke_scd2_snapshot',
        "'2026-01-01 00:00:00'::timestamp_ntz"
    ) -%}
    {%- set rendered = '---EVENT_SCD2---\n' ~ event_sql ~ '\n---SNAPSHOT_SCD2---\n' ~ snapshot_sql -%}
    {%- do log(rendered, info=true) -%}
    {{ return(rendered) }}
{%- endmacro %}
