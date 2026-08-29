{% macro generate_database_name(custom_database_name, node) -%}
    {{ return(enterprise_snowflake_framework.esf_generate_database_name(custom_database_name, node)) }}
{%- endmacro %}

{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ return(enterprise_snowflake_framework.esf_generate_schema_name(custom_schema_name, node)) }}
{%- endmacro %}
