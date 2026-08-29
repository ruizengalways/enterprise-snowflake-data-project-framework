{% macro esf_scd1_merge_sql(
    target_relation,
    source_relation,
    key_columns,
    order_columns,
    operation_column=none,
    delete_values=[]
) -%}
    {%- set latest_sql -%}
{{ enterprise_snowflake_framework.esf_latest_observation(
    source_relation,
    key_columns,
    order_columns
) }}
    {%- endset -%}

{{ enterprise_snowflake_framework.esf_merge_current_state_sql(
    target_relation,
    '(' ~ latest_sql ~ ')',
    key_columns,
    operation_column,
    delete_values
) }}
{%- endmacro %}
