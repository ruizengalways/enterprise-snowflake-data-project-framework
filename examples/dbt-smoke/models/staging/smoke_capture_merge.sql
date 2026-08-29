{{ config(
    pre_hook=enterprise_snowflake_framework.esf_merge_current_state_sql(
        'CAPTURE_CURRENT',
        'CAPTURE_CHANGES',
        ['id'],
        'source_operation',
        ['DELETE']
    )
) }}

select 1 as id
