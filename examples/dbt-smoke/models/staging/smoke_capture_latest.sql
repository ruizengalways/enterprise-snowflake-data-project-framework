with observations as (
    select 1 as id, 1 as source_sequence, 'old' as value
    union all
    select 1 as id, 2 as source_sequence, 'new' as value
)

{{ enterprise_snowflake_framework.esf_latest_observation(
    'observations',
    ['id'],
    ['source_sequence']
) }}
