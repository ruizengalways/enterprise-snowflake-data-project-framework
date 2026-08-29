{% macro esf_scd2_multiple_current_violations_sql(relation, key_columns) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
select
    {%- for key in keys %}
    {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
    {%- endfor %},
    count_if(_esf_is_current) as current_row_count
from {{ relation }}
group by
    {%- for key in keys %}
    {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
    {%- endfor %}
having count_if(_esf_is_current) > 1
{%- endmacro %}

{% macro esf_scd2_invalid_range_violations_sql(relation, key_columns) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
select
    {%- for key in keys %}
    {{ adapter.quote(key) }},
    {%- endfor %}
    _esf_valid_from,
    _esf_valid_to,
    _esf_version_ordinal
from {{ relation }}
where _esf_valid_from is null
   or (_esf_valid_to is not null and _esf_valid_to < _esf_valid_from)
   or (_esf_is_current and _esf_valid_to is not null)
   or (not _esf_is_current and _esf_valid_to is null)
{%- endmacro %}

{% macro esf_scd2_overlap_violations_sql(relation, key_columns) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
with intervals as (
    select
        source_history.*,
        max(coalesce(_esf_valid_to, '9999-12-31 23:59:59.999 +00:00'::timestamp_tz)) over (
            partition by
                {%- for key in keys %}
                {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            order by _esf_valid_from, _esf_version_ordinal
            rows between unbounded preceding and 1 preceding
        ) as _esf_previous_max_valid_to
    from {{ relation }} as source_history
)
select
    {%- for key in keys %}
    {{ adapter.quote(key) }},
    {%- endfor %}
    _esf_valid_from,
    _esf_valid_to,
    _esf_version_ordinal,
    _esf_previous_max_valid_to
from intervals
where _esf_previous_max_valid_to is not null
  and _esf_valid_from < _esf_previous_max_valid_to
{%- endmacro %}

{% macro esf_scd2_duplicate_version_violations_sql(relation, key_columns) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
select
    {%- for key in keys %}
    {{ adapter.quote(key) }},
    {%- endfor %}
    _esf_version_ordinal,
    count(*) as duplicate_count
from {{ relation }}
group by
    {%- for key in keys %}
    {{ adapter.quote(key) }},
    {%- endfor %}
    _esf_version_ordinal
having count(*) > 1
{%- endmacro %}

{% macro esf_scd2_invariant_summary_sql(relation, key_columns) -%}
select 'multiple_current' as invariant_name, count(*) as violation_count
from (
    {{ enterprise_snowflake_framework.esf_scd2_multiple_current_violations_sql(relation, key_columns) }}
)
union all
select 'invalid_range' as invariant_name, count(*) as violation_count
from (
    {{ enterprise_snowflake_framework.esf_scd2_invalid_range_violations_sql(relation, key_columns) }}
)
union all
select 'overlapping_ranges' as invariant_name, count(*) as violation_count
from (
    {{ enterprise_snowflake_framework.esf_scd2_overlap_violations_sql(relation, key_columns) }}
)
union all
select 'duplicate_version_ordinal' as invariant_name, count(*) as violation_count
from (
    {{ enterprise_snowflake_framework.esf_scd2_duplicate_version_violations_sql(relation, key_columns) }}
)
{%- endmacro %}
