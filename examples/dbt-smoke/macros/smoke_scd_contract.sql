{% macro smoke_scd_contract_sql() -%}
    {%- set target_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_target_table_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY',
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    true,
    'Patient history SCD2 target'
) }}
    {%- endset -%}

    {%- set multiple_current_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_multiple_current_violations_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY',
    ['patient_id']
) }}
    {%- endset -%}

    {%- set invalid_ranges_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_invalid_range_violations_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY',
    ['patient_id']
) }}
    {%- endset -%}

    {%- set overlap_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_overlap_violations_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY',
    ['patient_id']
) }}
    {%- endset -%}

    {%- set duplicate_version_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_duplicate_version_violations_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY',
    ['patient_id']
) }}
    {%- endset -%}

    {%- set summary_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_invariant_summary_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY',
    ['patient_id']
) }}
    {%- endset -%}

    {{ log(
        '---SCD2_TARGET---\n' ~ target_sql
        ~ '\n---MULTIPLE_CURRENT---\n' ~ multiple_current_sql
        ~ '\n---INVALID_RANGES---\n' ~ invalid_ranges_sql
        ~ '\n---OVERLAPS---\n' ~ overlap_sql
        ~ '\n---DUPLICATE_VERSION---\n' ~ duplicate_version_sql
        ~ '\n---INVARIANT_SUMMARY---\n' ~ summary_sql,
        info=true
    ) }}
    {{ return('SCD contract SQL rendered') }}
{%- endmacro %}
