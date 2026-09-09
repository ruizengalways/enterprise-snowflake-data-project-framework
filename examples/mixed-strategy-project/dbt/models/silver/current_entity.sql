{{ enterprise_snowflake_framework.esf_apply_dataset_config('current_entity') }}

select
    entity_id,
    value,
    source_updated_at
from {{ source('bronze', 'source_entity') }}
