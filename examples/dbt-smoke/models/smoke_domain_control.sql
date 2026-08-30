{%- set check_query -%}
select
    'freshness' as check_type,
    'domain_control_smoke' as check_name,
    'PASS' as status,
    'age_minutes' as measure_name,
    to_variant(1) as observed_value,
    object_construct('max_minutes', 5) as expected_value,
    object_construct('smoke', true) as details
{%- endset -%}

{{
    config(
        materialized='view',
        pre_hook=[
            enterprise_snowflake_framework.esf_domain_checkpoint_advance_call_sql(
                'HEALTH',
                'patient',
                'source_position',
                "object_construct('source_sequence', 12345)",
                'batch-123',
                'abc123'
            ),
            enterprise_snowflake_framework.esf_domain_pipeline_run_start_call_sql(
                'HEALTH',
                'run-123',
                1,
                'patient_capture',
                'patient',
                'abc123',
                "object_construct('project', 'health')",
                "object_construct('source_sequence', 12344)"
            ),
            enterprise_snowflake_framework.esf_domain_pipeline_run_finish_call_sql(
                'HEALTH',
                'run-123',
                1,
                'SUCCEEDED',
                "object_construct('source_sequence', 12345)",
                '100',
                '95',
                '10',
                '80',
                '5'
            ),
            enterprise_snowflake_framework.esf_domain_record_check_result_sql(
                'HEALTH',
                check_query,
                'run-123',
                1,
                'patient'
            )
        ]
    )
}}

{{ enterprise_snowflake_framework.esf_domain_checkpoint_read_sql(
    'HEALTH',
    'patient',
    'source_position'
) }}
