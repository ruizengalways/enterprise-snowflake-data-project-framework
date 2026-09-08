-- SCD2 history maintenance is a separate framework primitive.
-- This model stays readable and defines only the domain event shape consumed by it.
select
    entity_id,
    value,
    source_updated_at,
    source_operation,
    source_sequence,
    ingested_at
from {{ source('bronze', 'source_entity') }}
