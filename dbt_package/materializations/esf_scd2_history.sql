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
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(load.get('business_key', []), 'load.business_key') -%}
    {%- set ordering = enterprise_snowflake_framework.esf_require_columns(scd2.get('order_columns', []), 'load.scd2.order_columns') -%}
    {%- set tracked = enterprise_snowflake_framework.esf_require_columns(scd2.get('tracked_columns', []), 'load.scd2.tracked_columns') -%}
    {%- set effective_at = scd2.get('effective_at_column') -%}
    {%- set delete = scd2.get('delete', {}) -%}
    {%- set operation_column = delete.get('operation_column') -%}
    {%- set delete_values = delete.get('values', []) -%}
    {%- set target_relation = this -%}

    {% call statement('main') -%}
create or replace table {{ target_relation }} copy grants as
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
), ordered_events as (
    select
        enriched.*,
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
    from enriched
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

    {{ return({'relations': [target_relation]}) }}
{%- endmaterialization %}
