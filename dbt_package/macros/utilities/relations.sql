{% macro esf_require_columns(columns, label) -%}
    {%- if columns is not sequence or columns is string or columns | length == 0 -%}
        {{ exceptions.raise_compiler_error(label ~ ' must be a non-empty list of column names') }}
    {%- endif -%}
    {%- for column in columns -%}
        {%- if column is not string or column | trim == '' -%}
            {{ exceptions.raise_compiler_error(label ~ ' contains an invalid column name') }}
        {%- endif -%}
    {%- endfor -%}
    {{ return(columns) }}
{%- endmacro %}

{% macro esf_equal_keys(left_alias, right_alias, key_columns) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
    {%- for key in keys -%}
        EQUAL_NULL({{ left_alias }}.{{ adapter.quote(key) }}, {{ right_alias }}.{{ adapter.quote(key) }})
        {%- if not loop.last %} AND {% endif -%}
    {%- endfor -%}
{%- endmacro %}
