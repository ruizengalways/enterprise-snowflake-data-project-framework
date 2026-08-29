{% macro esf_generate_database_name(custom_database_name, node) -%}
    {{ return(env_var('DBT_DATABASE')) }}
{%- endmacro %}

{% macro esf_generate_schema_name(custom_schema_name, node) -%}
    {%- set layer = (custom_schema_name if custom_schema_name is not none else env_var('DBT_DEFAULT_SCHEMA', target.schema)) | upper -%}
    {%- set prefix = env_var('ESF_SCHEMA_PREFIX', '') | upper | trim -%}
    {%- if prefix -%}
        {{ return(prefix ~ '_' ~ layer) }}
    {%- else -%}
        {{ return(layer) }}
    {%- endif -%}
{%- endmacro %}
