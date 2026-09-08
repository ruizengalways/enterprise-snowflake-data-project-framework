{{ enterprise_snowflake_framework.esf_apply_dataset_config('current_dynamic') }}

select
    entity_id,
    value,
    source_updated_at,
    source_sequence,
    ingested_at
from {{ source('bronze', 'source_entity') }}
qualify row_number() over (
    partition by entity_id
    order by source_updated_at desc, source_sequence desc
) = 1
