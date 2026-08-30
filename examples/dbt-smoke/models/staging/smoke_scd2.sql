{{ config(materialized='view') }}

{{ enterprise_snowflake_framework.esf_scd2_history_select_for_dataset(
    'RAW_EVENTS',
    'smoke_scd2'
) }}
