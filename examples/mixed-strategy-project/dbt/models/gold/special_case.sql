{{ config(materialized='table') }}
{{ enterprise_snowflake_framework.esf_apply_dataset_config('special_case') }}

-- Custom means the domain owns implementation details; framework control-plane hooks remain reusable.
select
    entity_id,
    value
from {{ ref('historical_entity_current') }}
