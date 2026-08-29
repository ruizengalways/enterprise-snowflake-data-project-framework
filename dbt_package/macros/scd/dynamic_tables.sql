{% macro esf_scd1_dynamic_table_sql(
    target_relation,
    source_relation,
    warehouse,
    target_lag,
    key_columns,
    order_columns,
    refresh_mode='ADAPTIVE',
    operation_column=none,
    delete_values=[],
    initialize='ON_SCHEDULE'
) -%}
    {%- set latest_sql -%}
{{ enterprise_snowflake_framework.esf_latest_observation(
    source_relation,
    key_columns,
    order_columns
) }}
    {%- endset -%}
    {%- set select_sql -%}
with latest as (
    {{ latest_sql }}
)
select *
from latest
{%- if operation_column is not none and delete_values | length > 0 %}
where {{ adapter.quote(operation_column) }} not in (
    {%- for value in delete_values -%}
    '{{ value | replace("'", "''") }}'{% if not loop.last %}, {% endif %}
    {%- endfor -%}
)
{%- endif %}
    {%- endset -%}
{{ enterprise_snowflake_framework.esf_dynamic_table_projection_sql(
    target_relation,
    warehouse,
    target_lag,
    select_sql,
    refresh_mode,
    initialize
) }}
{%- endmacro %}
