{% macro esf_dynamic_table_projection_sql(
    target_relation,
    warehouse,
    target_lag,
    select_sql,
    refresh_mode='ADAPTIVE',
    initialize='ON_SCHEDULE'
) -%}
    {%- set mode = refresh_mode | upper -%}
    {%- set initialization = initialize | upper -%}
    {%- if mode not in ['INCREMENTAL', 'FULL', 'ADAPTIVE'] -%}
        {{ exceptions.raise_compiler_error(
            'Dynamic Table SELECT projection refresh_mode must be INCREMENTAL, FULL, or ADAPTIVE; '
            ~ 'AUTO is intentionally excluded from the production contract and CUSTOM_INCREMENTAL uses a different DML contract'
        ) }}
    {%- endif -%}
    {%- if initialization not in ['ON_CREATE', 'ON_SCHEDULE'] -%}
        {{ exceptions.raise_compiler_error('initialize must be ON_CREATE or ON_SCHEDULE') }}
    {%- endif -%}
    {%- if warehouse is not string or warehouse | trim == '' -%}
        {{ exceptions.raise_compiler_error('warehouse must be a non-empty Snowflake warehouse identifier') }}
    {%- endif -%}
    {%- if target_lag is not string or target_lag | trim == '' -%}
        {{ exceptions.raise_compiler_error('target_lag must be a non-empty Snowflake target lag such as 5 minutes') }}
    {%- endif -%}
    {%- if select_sql is not string or select_sql | trim == '' -%}
        {{ exceptions.raise_compiler_error('select_sql must be a non-empty SELECT statement') }}
    {%- endif -%}
create or alter dynamic table {{ target_relation }}
    target_lag = '{{ target_lag | replace("'", "''") }}'
    warehouse = {{ adapter.quote(warehouse) }}
    refresh_mode = {{ mode }}
    initialize = {{ initialization }}
as
{{ select_sql }}
{%- endmacro %}
