{{ enterprise_snowflake_framework.esf_apply_dataset_config('events') }}

select
    entity_id,
    value,
    source_updated_at,
    source_sequence,
    source_operation
from {{ source('bronze', 'source_entity') }}
