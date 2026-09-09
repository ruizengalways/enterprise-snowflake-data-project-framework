{# Domain projects can read only scoped views and mutate control state only through scoped procedures. #}

{% macro esf_domain_project_code(project_code) -%}
    {%- if project_code is not string or modules.re.fullmatch('^[A-Z][A-Z0-9_]{1,31}$', project_code | trim | upper) is none -%}
        {{ exceptions.raise_compiler_error('project_code must match ^[A-Z][A-Z0-9_]{1,31}$') }}
    {%- endif -%}
    {{ return(project_code | trim | upper) }}
{%- endmacro %}

{% macro esf_domain_control_relation(project_code, object_name) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {%- set object_name = object_name | trim | upper -%}
    {%- if object_name not in ['PIPELINE_CHECKPOINT', 'PIPELINE_RUN', 'PIPELINE_CHECK_RESULT'] -%}
        {{ exceptions.raise_compiler_error('unsupported domain control relation: ' ~ object_name) }}
    {%- endif -%}
    {{ return('PLATFORM_CONTROL.OPERATIONS.' ~ code ~ '_' ~ object_name) }}
{%- endmacro %}

{% macro esf_domain_control_procedure(project_code, procedure_name) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {%- set procedure_name = procedure_name | trim | upper -%}
    {%- if procedure_name not in ['ADVANCE_PIPELINE_CHECKPOINT', 'PIPELINE_RUN_START', 'PIPELINE_RUN_FINISH', 'RECORD_PIPELINE_CHECK_RESULT'] -%}
        {{ exceptions.raise_compiler_error('unsupported domain control procedure: ' ~ procedure_name) }}
    {%- endif -%}
    {{ return('PLATFORM_CONTROL.OPERATIONS.' ~ code ~ '_' ~ procedure_name) }}
{%- endmacro %}

{% macro esf_processing_checkpoint_kind(checkpoint_kind) -%}
    {%- set kind = checkpoint_kind | trim | lower -%}
    {# Framework checkpoints describe landed Snowflake data, never connector-owned LSN/cursor state. #}
    {%- if kind not in ['watermark', 'event_offset', 'snapshot_id', 'file_identity'] -%}
        {{ exceptions.raise_compiler_error('unsupported landed-data processing checkpoint_kind: ' ~ kind) }}
    {%- endif -%}
    {{ return(kind) }}
{%- endmacro %}

{% macro esf_domain_checkpoint_read_sql(project_code, dataset_id, checkpoint_kind) -%}
    {%- set kind = enterprise_snowflake_framework.esf_processing_checkpoint_kind(checkpoint_kind) -%}
select
    checkpoint_value,
    last_successful_batch_id,
    last_successful_at,
    last_git_sha,
    row_version
from {{ enterprise_snowflake_framework.esf_domain_control_relation(project_code, 'PIPELINE_CHECKPOINT') }}
where dataset_id = {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }}
  and checkpoint_kind = {{ enterprise_snowflake_framework.esf_sql_literal(kind) }}
{%- endmacro %}

{% macro esf_domain_checkpoint_advance_call_sql(project_code, dataset_id, checkpoint_kind, checkpoint_value_sql, batch_id, git_sha) -%}
    {%- set kind = enterprise_snowflake_framework.esf_processing_checkpoint_kind(checkpoint_kind) -%}
call {{ enterprise_snowflake_framework.esf_domain_control_procedure(project_code, 'ADVANCE_PIPELINE_CHECKPOINT') }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(kind) }},
    {{ checkpoint_value_sql }},
    {{ enterprise_snowflake_framework.esf_sql_literal(batch_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha) }}
)
{%- endmacro %}

{% macro esf_domain_pipeline_run_start_call_sql(project_code, run_id, attempt_number, pipeline_id, dataset_id=none, git_sha=none, query_tag_expression='NULL', checkpoint_before_expression='NULL') -%}
call {{ enterprise_snowflake_framework.esf_domain_control_procedure(project_code, 'PIPELINE_RUN_START') }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(run_id) }},
    {{ attempt_number | int }},
    {{ enterprise_snowflake_framework.esf_sql_literal(pipeline_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha) }},
    {{ query_tag_expression }},
    {{ checkpoint_before_expression }}
)
{%- endmacro %}

{% macro esf_domain_pipeline_run_finish_call_sql(project_code, run_id, attempt_number, status, checkpoint_after_expression='NULL', rows_read_expression='NULL', rows_written_expression='NULL', rows_inserted_expression='NULL', rows_updated_expression='NULL', rows_deleted_expression='NULL', error_class=none, error_message=none, details_expression='NULL') -%}
    {%- set status = status | upper -%}
    {%- if status not in ['SUCCEEDED', 'FAILED', 'CANCELLED'] -%}
        {{ exceptions.raise_compiler_error('invalid pipeline finish status: ' ~ status) }}
    {%- endif -%}
call {{ enterprise_snowflake_framework.esf_domain_control_procedure(project_code, 'PIPELINE_RUN_FINISH') }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(run_id) }},
    {{ attempt_number | int }},
    {{ enterprise_snowflake_framework.esf_sql_literal(status) }},
    {{ checkpoint_after_expression }},
    {{ rows_read_expression }},
    {{ rows_written_expression }},
    {{ rows_inserted_expression }},
    {{ rows_updated_expression }},
    {{ rows_deleted_expression }},
    {{ enterprise_snowflake_framework.esf_sql_literal(error_class) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(error_message) }},
    {{ details_expression }}
)
{%- endmacro %}

{% macro esf_domain_record_check_result_sql(project_code, check_query, run_id, attempt_number, dataset_id) -%}
execute immediate $$
declare
    check_results resultset default ({{ check_query }});
    check_cursor cursor for check_results;
begin
    for check_row in check_cursor do
        call {{ enterprise_snowflake_framework.esf_domain_control_procedure(project_code, 'RECORD_PIPELINE_CHECK_RESULT') }}(
            {{ enterprise_snowflake_framework.esf_sql_literal(run_id) }},
            {{ attempt_number | int }},
            {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
            check_row.check_type,
            check_row.check_name,
            check_row.status,
            check_row.measure_name,
            check_row.observed_value,
            check_row.expected_value,
            check_row.details
        );
    end for;
    return 'pipeline check results recorded';
end;
$$
{%- endmacro %}
