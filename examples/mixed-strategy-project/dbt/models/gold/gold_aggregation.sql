{{ enterprise_snowflake_framework.esf_apply_dataset_config('gold_aggregation') }}

select
    value,
    count(*) as entity_count
from {{ ref('historical_entity_current') }}
group by
    value
