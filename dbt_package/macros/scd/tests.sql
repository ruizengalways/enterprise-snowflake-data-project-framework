{% test esf_scd2_one_current(model, key_columns) -%}
{{ enterprise_snowflake_framework.esf_scd2_multiple_current_violations_sql(model, key_columns) }}
{%- endtest %}

{% test esf_scd2_valid_ranges(model, key_columns) -%}
{{ enterprise_snowflake_framework.esf_scd2_invalid_range_violations_sql(model, key_columns) }}
{%- endtest %}

{% test esf_scd2_no_overlaps(model, key_columns) -%}
{{ enterprise_snowflake_framework.esf_scd2_overlap_violations_sql(model, key_columns) }}
{%- endtest %}

{% test esf_scd2_unique_version_ordinal(model, key_columns) -%}
{{ enterprise_snowflake_framework.esf_scd2_duplicate_version_violations_sql(model, key_columns) }}
{%- endtest %}
