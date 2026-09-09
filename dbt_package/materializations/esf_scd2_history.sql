{% materialization esf_scd2_history, adapter='snowflake' -%}
    {%- set meta = config.get('meta', {}) -%}
    {%- set dataset_id = meta.get('esf_dataset_id') -%}
    {%- if not dataset_id -%}
        {{ exceptions.raise_compiler_error('esf_scd2_history requires meta.esf_dataset_id') }}
    {%- endif -%}
    {%- set dataset = enterprise_snowflake_framework.esf_dataset_metadata(dataset_id) -%}
    {%- set load = dataset.get('load', {}) -%}
    {%- if load.get('strategy') != 'scd2' -%}
        {{ exceptions.raise_compiler_error('esf_scd2_history requires load.strategy=scd2: ' ~ dataset_id) }}
    {%- endif -%}
    {%- set scd2 = load.get('scd2', {}) -%}
    {%- if scd2.get('late_arrival', {}).get('strategy') != 'rebuild_affected_keys' -%}
        {{ exceptions.raise_compiler_error('esf_scd2_history requires late_arrival.strategy=rebuild_affected_keys: ' ~ dataset_id) }}
    {%- endif -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(load.get('business_key', []), 'load.business_key') -%}
    {%- set ordering = enterprise_snowflake_framework.esf_require_columns(scd2.get('order_columns', []), 'load.scd2.order_columns') -%}
    {%- set tracked = enterprise_snowflake_framework.esf_require_columns(scd2.get('tracked_columns', []), 'load.scd2.tracked_columns') -%}
    {%- set effective_at = scd2.get('effective_at_column') -%}
    {%- set delete = scd2.get('delete', {}) -%}
    {%- set operation_column = delete.get('operation_column') -%}
    {%- set delete_values = delete.get('values', []) -%}
    {%- set target_relation = this -%}
    {%- set event_relation = target_relation.incorporate(path={'identifier': target_relation.identifier ~ '__ESF_EVENTS'}) -%}
    {%- set stage_relation = make_temp_relation(target_relation, '__esf_stage') -%}
    {%- set affected_relation = make_temp_relation(target_relation, '__esf_affected') -%}
    {%- set rebuild_relation = make_temp_relation(target_relation, '__esf_rebuild') -%}

    {% call statement('stage_source') -%}
create or replace temporary table {{ stage_relation }} as
with source_rows as (
    {{ sql }}
), enriched as (
    select
        source_rows.*,
        hash(
            {%- for column in tracked %}
            source_rows.{{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
            {%- endfor %}
        ) as _esf_record_hash,
        {%- if operation_column and delete_values | length > 0 %}
        source_rows.{{ adapter.quote(operation_column) }} in (
            {%- for value in delete_values -%}
            '{{ value | replace("'", "''") }}'{% if not loop.last %}, {% endif %}
            {%- endfor -%}
        )
        {%- else %}
        false
        {%- endif %} as _esf_is_delete
    from source_rows
), deterministic_identity as (
    select
        enriched.*,
        row_number() over (
            partition by
                {%- for key in keys %}
                {{ adapter.quote(key) }},
                {%- endfor %}
                {%- for column in ordering %}
                {{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by _esf_record_hash desc, _esf_is_delete desc
        ) as _esf_identity_rank
    from enriched
)
select * exclude (_esf_identity_rank)
from deterministic_identity
where _esf_identity_rank = 1
    {%- endcall %}

    {% call statement('ensure_event_ledger') -%}
create table if not exists {{ event_relation }} as
select * from {{ stage_relation }} where 1 = 0
    {%- endcall %}

    {% call statement('ensure_history_target') -%}
create table if not exists {{ target_relation }} as
select
    staged.* exclude (_esf_record_hash, _esf_is_delete),
    cast(null as number) as version_order,
    staged.{{ adapter.quote(effective_at) }} as valid_from,
    staged.{{ adapter.quote(effective_at) }} as valid_to,
    false as is_current
from {{ stage_relation }} as staged
where 1 = 0
    {%- endcall %}

    {% call statement('identify_affected_keys') -%}
create or replace temporary table {{ affected_relation }} as
select distinct
    {%- for key in keys %}
    staged.{{ adapter.quote(key) }} as {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
    {%- endfor %}
from {{ stage_relation }} as staged
where not exists (
    select 1
    from {{ event_relation }} as existing
    where {{ enterprise_snowflake_framework.esf_equal_keys('existing', 'staged', keys + ordering) }}
)
union
select distinct
    {%- for key in keys %}
    events.{{ adapter.quote(key) }} as {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
    {%- endfor %}
from {{ event_relation }} as events
where not exists (
    select 1
    from {{ target_relation }} as history
    where {{ enterprise_snowflake_framework.esf_equal_keys('history', 'events', keys) }}
)
    {%- endcall %}

    {% call statement('build_affected_history') -%}
create or replace temporary table {{ rebuild_relation }} as
with source_rows as (
    select events.*
    from {{ event_relation }} as events
    inner join {{ affected_relation }} as affected
        on {{ enterprise_snowflake_framework.esf_equal_keys('events', 'affected', keys) }}

    union all

    select staged.*
    from {{ stage_relation }} as staged
    inner join {{ affected_relation }} as affected
        on {{ enterprise_snowflake_framework.esf_equal_keys('staged', 'affected', keys) }}
    where not exists (
        select 1
        from {{ event_relation }} as existing
        where {{ enterprise_snowflake_framework.esf_equal_keys('existing', 'staged', keys + ordering) }}
    )
), ordered_events as (
    select
        source_rows.*,
        row_number() over (
            partition by
                {%- for key in keys %}
                {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by
                {%- for column in ordering %}
                {{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
        ) as _esf_event_ordinal,
        lag(_esf_record_hash) over (
            partition by
                {%- for key in keys %}
                {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by
                {%- for column in ordering %}
                {{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
        ) as _esf_prev_hash,
        lag(_esf_is_delete) over (
            partition by
                {%- for key in keys %}
                {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by
                {%- for column in ordering %}
                {{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
        ) as _esf_prev_is_delete
    from source_rows
), state_changes as (
    select *
    from ordered_events
    where _esf_event_ordinal = 1
       or _esf_is_delete
       or coalesce(_esf_prev_is_delete, false)
       or not equal_null(_esf_record_hash, _esf_prev_hash)
), intervalized as (
    select
        state_changes.*,
        row_number() over (
            partition by
                {%- for key in keys %}
                {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by
                {%- for column in ordering %}
                {{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
        ) as version_order,
        lead({{ adapter.quote(effective_at) }}) over (
            partition by
                {%- for key in keys %}
                {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by
                {%- for column in ordering %}
                {{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
        ) as _esf_next_effective_at
    from state_changes
)
select
    intervalized.* exclude (
        _esf_record_hash,
        _esf_is_delete,
        _esf_event_ordinal,
        _esf_prev_hash,
        _esf_prev_is_delete,
        _esf_next_effective_at
    ),
    {{ adapter.quote(effective_at) }} as valid_from,
    _esf_next_effective_at as valid_to,
    _esf_next_effective_at is null as is_current
from intervalized
where not _esf_is_delete
    {%- endcall %}

    {% call statement('main') -%}
begin transaction;

insert into {{ event_relation }}
select staged.*
from {{ stage_relation }} as staged
inner join {{ affected_relation }} as affected
    on {{ enterprise_snowflake_framework.esf_equal_keys('staged', 'affected', keys) }}
where not exists (
    select 1
    from {{ event_relation }} as existing
    where {{ enterprise_snowflake_framework.esf_equal_keys('existing', 'staged', keys + ordering) }}
);

delete from {{ target_relation }} as history
using {{ affected_relation }} as affected
where {{ enterprise_snowflake_framework.esf_equal_keys('history', 'affected', keys) }};

insert into {{ target_relation }}
select * from {{ rebuild_relation }};

commit;
    {%- endcall %}

    {% call statement('cleanup') -%}
drop table if exists {{ stage_relation }};
drop table if exists {{ affected_relation }};
drop table if exists {{ rebuild_relation }};
    {%- endcall %}

    {{ return({'relations': [target_relation]}) }}
{%- endmaterialization %}
