{{ config(materialized='view') }}

select
    entity_id,
    value,
    source_updated_at,
    valid_from,
    valid_to,
    version_order
from {{ ref('historical_entity_history') }}
where is_current = true
