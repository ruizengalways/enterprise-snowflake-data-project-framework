{% macro esf_scd2_invariant_violations_sql(relation, key_columns) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
with history as (
    select
        source_history.*,
        max(coalesce(valid_to, '9999-12-31 23:59:59.999 +00:00'::timestamp_tz)) over (
            partition by
                {%- for key in keys %}
                {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by valid_from, version_order
            rows between unbounded preceding and 1 preceding
        ) as previous_max_valid_to
    from {{ relation }} as source_history
), violations as (
    select 'multiple_current' as invariant_name
    from {{ relation }}
    group by
        {%- for key in keys %}
        {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
        {%- endfor %}
    having count_if(is_current) > 1

    union all

    select 'invalid_range' as invariant_name
    from {{ relation }}
    where valid_from is null
       or (valid_to is not null and valid_to < valid_from)
       or (is_current and valid_to is not null)
       or (not is_current and valid_to is null)

    union all

    select 'overlap' as invariant_name
    from history
    where previous_max_valid_to is not null
      and valid_from < previous_max_valid_to
)
select * from violations
{%- endmacro %}
