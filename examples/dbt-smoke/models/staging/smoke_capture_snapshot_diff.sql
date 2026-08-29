with current_snapshot as (
    select 1 as id, 'new-hash' as record_hash, 'new' as value
),
previous_snapshot as (
    select 1 as id, 'old-hash' as record_hash, 'old' as value
)

{{ enterprise_snowflake_framework.esf_snapshot_diff(
    'current_snapshot',
    'previous_snapshot',
    ['id'],
    'record_hash'
) }}
