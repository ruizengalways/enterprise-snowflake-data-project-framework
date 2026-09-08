{{ enterprise_snowflake_framework.esf_apply_dataset_config('current_merge') }}

select
    entity_id,
    value,
    source_updated_at,
    source_operation,
    source_sequence,
    ingested_at
from {{ source('bronze', 'source_entity') }}
