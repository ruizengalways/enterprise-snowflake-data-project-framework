{{ config(
    materialized='view',
    pre_hook=enterprise_snowflake_framework.esf_scd2_target_table_sql(
        'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY',
        'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
        true,
        'Patient history SCD2 target'
    )
) }}

{{ enterprise_snowflake_framework.esf_scd2_invariant_summary_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY',
    ['patient_id']
) }}
