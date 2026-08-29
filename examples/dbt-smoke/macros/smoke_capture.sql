{% macro smoke_capture_sql() -%}
    {%- set latest_sql -%}
{{ enterprise_snowflake_framework.esf_latest_observation(
    'OBSERVATIONS',
    ['id'],
    ['source_sequence']
) }}
    {%- endset -%}

    {%- set diff_sql -%}
{{ enterprise_snowflake_framework.esf_snapshot_diff(
    'CURRENT_SNAPSHOT',
    'PREVIOUS_SNAPSHOT',
    ['id'],
    'record_hash'
) }}
    {%- endset -%}

    {%- set standard_stream_sql -%}
{{ enterprise_snowflake_framework.esf_standard_stream_sql(
    'CI_HEALTH.PR_123_STAGING.PATIENT_CURRENT_STREAM',
    'CI_HEALTH.PR_123_STAGING.PATIENT_CURRENT_SOURCE',
    false,
    'Consume native Snowflake row changes including updates and deletes'
) }}
    {%- endset -%}

    {%- set stream_sql -%}
{{ enterprise_snowflake_framework.esf_append_only_stream_sql(
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT_STREAM',
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    false,
    'Consume immutable patient CDC events'
) }}
    {%- endset -%}

    {%- set task_sql -%}
{{ enterprise_snowflake_framework.esf_triggered_task_sql(
    'CI_HEALTH.PR_123_STAGING.PROCESS_PATIENT_EVENT',
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT_STREAM',
    'WH_HEALTH_CI',
    'insert into CI_HEALTH.PR_123_STAGING.PATIENT_EVENT_CONSUMED select * from CI_HEALTH.PR_123_STAGING.PATIENT_EVENT_STREAM',
    30,
    3600000,
    1,
    3,
    'NO_OVERLAP',
    'Process immutable patient CDC events',
    true
) }}
    {%- endset -%}

    {%- set task_history_sql -%}
{{ enterprise_snowflake_framework.esf_task_history_sql(
    'PROCESS_PATIENT_EVENT',
    100,
    false
) }}
    {%- endset -%}

    {%- set task_graphs_sql -%}
{{ enterprise_snowflake_framework.esf_complete_task_graphs_sql(
    'PROCESS_PATIENT_EVENT',
    100,
    false
) }}
    {%- endset -%}

    {%- set checkpoint_read_sql -%}
{{ enterprise_snowflake_framework.esf_checkpoint_read_sql(
    'HEALTH',
    'patient',
    'source_position'
) }}
    {%- endset -%}

    {%- set checkpoint_advance_sql -%}
{{ enterprise_snowflake_framework.esf_checkpoint_advance_call_sql(
    'HEALTH',
    'patient',
    'source_position',
    "object_construct('source_sequence', 12345)",
    'batch-123',
    'abc123'
) }}
    {%- endset -%}

    {%- set native_freshness_schedule_sql -%}
{{ enterprise_snowflake_framework.esf_native_dmf_schedule_sql(
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    'TRIGGER_ON_CHANGES',
    'TABLE'
) }}
    {%- endset -%}

    {%- set native_freshness_dmf_sql -%}
{{ enterprise_snowflake_framework.esf_native_freshness_dmf_sql(
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    60,
    120,
    none,
    'TABLE'
) }}
    {%- endset -%}

    {%- set native_dmf_status_sql -%}
{{ enterprise_snowflake_framework.esf_native_dmf_expectation_status_sql(
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    'TABLE'
) }}
    {%- endset -%}

    {%- set reconciliation_sql -%}
{{ enterprise_snowflake_framework.esf_reconciliation_compare_sql(
    'CI_HEALTH.PR_123_STAGING.PATIENT_SOURCE',
    'CI_HEALTH.PR_123_STAGING.PATIENT_TARGET',
    'source',
    'target',
    ['patient_id'],
    'source_updated_at'
) }}
    {%- endset -%}

    {%- set run_start_sql -%}
{{ enterprise_snowflake_framework.esf_pipeline_run_start_sql(
    'PLATFORM_CONTROL.OPERATIONS.PIPELINE_RUN',
    'run-123',
    1,
    'HEALTH',
    'CI',
    'patient_capture',
    'patient',
    'abc123'
) }}
    {%- endset -%}

    {%- set run_finish_sql -%}
{{ enterprise_snowflake_framework.esf_pipeline_run_finish_sql(
    'PLATFORM_CONTROL.OPERATIONS.PIPELINE_RUN',
    'run-123',
    1,
    'SUCCEEDED',
    "object_construct('source_sequence', 12345)",
    '100',
    '95',
    '10',
    '80',
    '5'
) }}
    {%- endset -%}

    {%- set scd1_sql -%}
{{ enterprise_snowflake_framework.esf_scd1_merge_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_CURRENT',
    'CI_HEALTH.PR_123_STAGING.PATIENT_CHANGES',
    ['patient_id'],
    ['source_sequence'],
    'op',
    ['D']
) }}
    {%- endset -%}

    {%- set scd2_history_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_event_history_select(
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    ['patient_id'],
    'source_updated_at',
    ['source_updated_at', 'source_sequence'],
    'record_hash',
    'op',
    ['D']
) }}
    {%- endset -%}

    {%- set scd2_rebuild_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_rebuild_affected_keys_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY',
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    'CI_HEALTH.PR_123_STAGING.PATIENT_AFFECTED_KEYS',
    ['patient_id'],
    'source_updated_at',
    ['source_updated_at', 'source_sequence'],
    'record_hash',
    'op',
    ['D']
) }}
    {%- endset -%}

    {%- set scd2_snapshot_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_snapshot_apply_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_SNAPSHOT_HISTORY',
    'CI_HEALTH.PR_123_STAGING.PATIENT_SNAPSHOT',
    ['patient_id'],
    'record_hash',
    "to_timestamp_tz('2026-08-29 00:00:00 +00:00')"
) }}
    {%- endset -%}

    {%- set scd2_stream_task_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_stream_task_sql(
    'CI_HEALTH.PR_123_CANONICAL.PROCESS_PATIENT_HISTORY',
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT_STREAM',
    'CI_HEALTH.PR_123_STAGING.PATIENT_AFFECTED_KEYS',
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY',
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    'WH_HEALTH_CI',
    ['patient_id'],
    'source_updated_at',
    ['source_updated_at', 'source_sequence'],
    'record_hash',
    'op',
    ['D'],
    30,
    3600000,
    1,
    3,
    'Transactional SCD2 stream consumer',
    false
) }}
    {%- endset -%}

    {%- set scd1_dt_sql -%}
{{ enterprise_snowflake_framework.esf_scd1_dynamic_table_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_CURRENT_DT',
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    'WH_HEALTH_CI',
    '5 minutes',
    ['patient_id'],
    ['source_sequence'],
    'INCREMENTAL',
    'op',
    ['D']
) }}
    {%- endset -%}

    {%- set scd2_dt_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_dynamic_table_sql(
    'CI_HEALTH.PR_123_CANONICAL.PATIENT_HISTORY_DT',
    'CI_HEALTH.PR_123_STAGING.PATIENT_EVENT',
    'WH_HEALTH_CI',
    '5 minutes',
    ['patient_id'],
    'source_updated_at',
    ['source_updated_at', 'source_sequence'],
    'record_hash',
    'INCREMENTAL',
    'op',
    ['D']
) }}
    {%- endset -%}

    {{ log(
        '---LATEST---\n' ~ latest_sql
        ~ '\n---SNAPSHOT_DIFF---\n' ~ diff_sql
        ~ '\n---STANDARD_STREAM---\n' ~ standard_stream_sql
        ~ '\n---APPEND_ONLY_STREAM---\n' ~ stream_sql
        ~ '\n---TRIGGERED_TASK---\n' ~ task_sql
        ~ '\n---TASK_HISTORY---\n' ~ task_history_sql
        ~ '\n---TASK_GRAPHS---\n' ~ task_graphs_sql
        ~ '\n---CHECKPOINT_READ---\n' ~ checkpoint_read_sql
        ~ '\n---CHECKPOINT_ADVANCE---\n' ~ checkpoint_advance_sql
        ~ '\n---NATIVE_FRESHNESS_SCHEDULE---\n' ~ native_freshness_schedule_sql
        ~ '\n---NATIVE_FRESHNESS_DMF---\n' ~ native_freshness_dmf_sql
        ~ '\n---NATIVE_DMF_STATUS---\n' ~ native_dmf_status_sql
        ~ '\n---RECONCILIATION---\n' ~ reconciliation_sql
        ~ '\n---RUN_START---\n' ~ run_start_sql
        ~ '\n---RUN_FINISH---\n' ~ run_finish_sql
        ~ '\n---SCD1---\n' ~ scd1_sql
        ~ '\n---SCD2_HISTORY---\n' ~ scd2_history_sql
        ~ '\n---SCD2_REBUILD---\n' ~ scd2_rebuild_sql
        ~ '\n---SCD2_SNAPSHOT---\n' ~ scd2_snapshot_sql
        ~ '\n---SCD2_STREAM_TASK---\n' ~ scd2_stream_task_sql
        ~ '\n---SCD1_DYNAMIC_TABLE---\n' ~ scd1_dt_sql
        ~ '\n---SCD2_DYNAMIC_TABLE---\n' ~ scd2_dt_sql,
        info=true
    ) }}
    {{ return('capture SQL rendered') }}
{%- endmacro %}
