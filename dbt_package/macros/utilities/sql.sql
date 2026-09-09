{% macro esf_sql_literal(value) -%}
    {%- if value is none -%}
        NULL
    {%- else -%}
        '{{ value | string | replace("'", "''") }}'
    {%- endif -%}
{%- endmacro %}
