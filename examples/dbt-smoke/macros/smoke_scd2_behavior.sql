{% macro smoke_scd2_behavior_sql() -%}
    {%- set fixture_relation -%}
(
    select
        column1::varchar as patient_id,
        column2::timestamp_tz as source_updated_at,
        column3::number as source_sequence,
        column4::varchar as record_hash,
        column5::varchar as op,
        column6::varchar as payload
    from values
        -- Exact duplicate replay: identical ordering identity and state must not
        -- create a second SCD2 version.
        ('A', '2026-01-01 00:00:00 +00:00', 10, 'a1', 'I', 'alpha-v1'),
        ('A', '2026-01-01 00:00:00 +00:00', 10, 'a1', 'I', 'alpha-v1'),
        -- A later source event with the same state is also a no-op.
        ('A', '2026-01-02 00:00:00 +00:00', 20, 'a1', 'U', 'alpha-v1'),
        ('A', '2026-01-03 00:00:00 +00:00', 30, 'a2', 'U', 'alpha-v2'),
        ('A', '2026-01-04 00:00:00 +00:00', 40, 'a2', 'D', null),
        -- Reinsert after delete opens a new current version and preserves the gap.
        ('A', '2026-01-05 00:00:00 +00:00', 50, 'a3', 'I', 'alpha-v3'),

        ('B', '2026-02-01 00:00:00 +00:00', 10, 'b1', 'I', 'bravo-v1'),
        ('B', '2026-02-02 00:00:00 +00:00', 30, 'b3', 'U', 'bravo-v3'),
        -- Physically listed after b3 to represent a late-arriving event. History
        -- must be rebuilt by source effective time + deterministic source sequence.
        ('B', '2026-02-01 12:00:00 +00:00', 20, 'b2', 'U', 'bravo-v2'),

        -- Equal effective timestamps are resolved by source_sequence. A zero-length
        -- interval is valid and preserves both real source changes.
        ('C', '2026-03-01 00:00:00 +00:00', 10, 'c1', 'I', 'charlie-v1'),
        ('C', '2026-03-01 00:00:00 +00:00', 20, 'c2', 'U', 'charlie-v2')
)
    {%- endset -%}

    {%- set actual_history_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_event_history_select(
    fixture_relation,
    ['patient_id'],
    'source_updated_at',
    ['source_updated_at', 'source_sequence'],
    'record_hash',
    'op',
    ['D']
) }}
    {%- endset -%}

with actual_history as (
    {{ actual_history_sql }}
), actual as (
    select
        patient_id,
        record_hash,
        source_sequence,
        _esf_valid_from,
        _esf_valid_to,
        _esf_is_current,
        _esf_version_ordinal
    from actual_history
), expected as (
    select
        column1::varchar as patient_id,
        column2::varchar as record_hash,
        column3::number as source_sequence,
        column4::timestamp_tz as _esf_valid_from,
        column5::timestamp_tz as _esf_valid_to,
        column6::boolean as _esf_is_current,
        column7::number as _esf_version_ordinal
    from values
        ('A', 'a1', 10, '2026-01-01 00:00:00 +00:00', '2026-01-03 00:00:00 +00:00', false, 1),
        ('A', 'a2', 30, '2026-01-03 00:00:00 +00:00', '2026-01-04 00:00:00 +00:00', false, 2),
        ('A', 'a3', 50, '2026-01-05 00:00:00 +00:00', null, true, 4),
        ('B', 'b1', 10, '2026-02-01 00:00:00 +00:00', '2026-02-01 12:00:00 +00:00', false, 1),
        ('B', 'b2', 20, '2026-02-01 12:00:00 +00:00', '2026-02-02 00:00:00 +00:00', false, 2),
        ('B', 'b3', 30, '2026-02-02 00:00:00 +00:00', null, true, 3),
        ('C', 'c1', 10, '2026-03-01 00:00:00 +00:00', '2026-03-01 00:00:00 +00:00', false, 1),
        ('C', 'c2', 20, '2026-03-01 00:00:00 +00:00', null, true, 2)
), missing_expected as (
    select * from expected
    minus
    select * from actual
), unexpected_actual as (
    select * from actual
    minus
    select * from expected
)
select 'MISSING_EXPECTED' as mismatch_type, missing_expected.*
from missing_expected
union all by name
select 'UNEXPECTED_ACTUAL' as mismatch_type, unexpected_actual.*
from unexpected_actual
order by patient_id, _esf_version_ordinal, mismatch_type
{%- endmacro %}

{% macro smoke_scd2_behavior_fixture_sql() -%}
    {%- set sql -%}
{{ smoke_scd2_behavior_sql() }}
    {%- endset -%}
    {{ log('---SCD2_BEHAVIOR_FIXTURE---\n' ~ sql, info=true) }}
    {{ return('SCD2 behavior fixture rendered') }}
{%- endmacro %}
