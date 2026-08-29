{{ config(
    pre_hook=enterprise_snowflake_framework.esf_dynamic_table_projection_sql(
        'DT_CAPTURE_PROJECTION',
        'WH_HEALTH_CI',
        '5 minutes',
        'select 1 as id',
        'INCREMENTAL',
        'ON_SCHEDULE'
    )
) }}

select 1 as id
