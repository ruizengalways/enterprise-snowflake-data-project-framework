{% macro esf_scd2_event_history_select(
    event_relation,
    key_columns,
    effective_at_column,
    order_columns,
    hash_column,
    operation_column=none,
    delete_values=[],
    key_filter_relation=none
) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
    {%- set ordering = enterprise_snowflake_framework.esf_require_columns(order_columns, 'order_columns') -%}
    {%- if effective_at_column not in ordering -%}
        {{ exceptions.raise_compiler_error('effective_at_column must be included in order_columns for SCD2 event history') }}
    {%- endif -%}
    {%- if delete_values is string -%}
        {{ exceptions.raise_compiler_error('delete_values must be a list') }}
    {%- endif -%}

with ordered_events as (
    select
        events.*,
        row_number() over (
            partition by
                {%- for key in keys %}
                events.{{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by
                {%- for column in ordering %}
                events.{{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
        ) as _esf_event_ordinal,
        lag(events.{{ adapter.quote(hash_column) }}) over (
            partition by
                {%- for key in keys %}
                events.{{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by
                {%- for column in ordering %}
                events.{{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
        ) as _esf_prev_hash,
        {%- if operation_column is not none and delete_values | length > 0 %}
        events.{{ adapter.quote(operation_column) }} in (
            {%- for value in delete_values -%}
            '{{ value | replace("'", "''") }}'{% if not loop.last %}, {% endif %}
            {%- endfor -%}
        )
        {%- else %}
        false
        {%- endif %} as _esf_is_delete,
        lag(
            {%- if operation_column is not none and delete_values | length > 0 %}
            events.{{ adapter.quote(operation_column) }} in (
                {%- for value in delete_values -%}
                '{{ value | replace("'", "''") }}'{% if not loop.last %}, {% endif %}
                {%- endfor -%}
            )
            {%- else %}
            false
            {%- endif %}
        ) over (
            partition by
                {%- for key in keys %}
                events.{{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by
                {%- for column in ordering %}
                events.{{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
        ) as _esf_prev_is_delete
    from {{ event_relation }} as events
    {%- if key_filter_relation is not none %}
    where exists (
        select 1
        from {{ key_filter_relation }} as affected
        where {{ enterprise_snowflake_framework.esf_equal_keys('events', 'affected', keys) }}
    )
    {%- endif %}
), state_changes as (
    select *
    from ordered_events
    where _esf_event_ordinal = 1
       or _esf_is_delete
       or coalesce(_esf_prev_is_delete, false)
       or not equal_null({{ adapter.quote(hash_column) }}, _esf_prev_hash)
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
        ) as _esf_version_ordinal,
        lead({{ adapter.quote(effective_at_column) }}) over (
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
        _esf_event_ordinal,
        _esf_prev_hash,
        _esf_is_delete,
        _esf_prev_is_delete,
        _esf_version_ordinal,
        _esf_next_effective_at
    ),
    {{ adapter.quote(effective_at_column) }} as _esf_valid_from,
    _esf_next_effective_at as _esf_valid_to,
    _esf_next_effective_at is null as _esf_is_current,
    _esf_version_ordinal as _esf_version_ordinal
from intervalized
where not _esf_is_delete
{%- endmacro %}

{% macro esf_scd2_rebuild_affected_keys_sql(
    target_relation,
    event_relation,
    affected_keys_relation,
    key_columns,
    effective_at_column,
    order_columns,
    hash_column,
    operation_column=none,
    delete_values=[]
) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
begin transaction;

delete from {{ target_relation }} as target
using {{ affected_keys_relation }} as affected
where {{ enterprise_snowflake_framework.esf_equal_keys('target', 'affected', keys) }};

insert into {{ target_relation }}
{{ enterprise_snowflake_framework.esf_scd2_event_history_select(
    event_relation,
    keys,
    effective_at_column,
    order_columns,
    hash_column,
    operation_column,
    delete_values,
    affected_keys_relation
) }};

commit;
{%- endmacro %}

{% macro esf_scd2_snapshot_apply_sql(
    target_relation,
    snapshot_relation,
    key_columns,
    hash_column,
    effective_at_expression='current_timestamp()'
) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
    {%- set sentinel = keys[0] -%}
begin transaction;

update {{ target_relation }} as target
set
    _esf_valid_to = {{ effective_at_expression }},
    _esf_is_current = false
from {{ snapshot_relation }} as snapshot
where target._esf_is_current
  and {{ enterprise_snowflake_framework.esf_equal_keys('target', 'snapshot', keys) }}
  and not equal_null(
      target.{{ adapter.quote(hash_column) }},
      snapshot.{{ adapter.quote(hash_column) }}
  );

update {{ target_relation }} as target
set
    _esf_valid_to = {{ effective_at_expression }},
    _esf_is_current = false
where target._esf_is_current
  and not exists (
      select 1
      from {{ snapshot_relation }} as snapshot
      where {{ enterprise_snowflake_framework.esf_equal_keys('target', 'snapshot', keys) }}
  );

insert into {{ target_relation }}
select
    snapshot.*,
    {{ effective_at_expression }} as _esf_valid_from,
    null::timestamp_tz as _esf_valid_to,
    true as _esf_is_current,
    coalesce(previous.max_version_ordinal, 0) + 1 as _esf_version_ordinal
from {{ snapshot_relation }} as snapshot
left join {{ target_relation }} as current_target
    on current_target._esf_is_current
   and {{ enterprise_snowflake_framework.esf_equal_keys('current_target', 'snapshot', keys) }}
left join (
    select
        {%- for key in keys %}
        {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
        {%- endfor %},
        max(_esf_version_ordinal) as max_version_ordinal
    from {{ target_relation }}
    group by
        {%- for key in keys %}
        {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
        {%- endfor %}
) as previous
    on {{ enterprise_snowflake_framework.esf_equal_keys('previous', 'snapshot', keys) }}
where current_target.{{ adapter.quote(sentinel) }} is null;

commit;
{%- endmacro %}
