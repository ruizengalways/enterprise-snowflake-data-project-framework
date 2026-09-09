{#
  Project-runtime access to shared PLATFORM_CONTROL state must use the
  domain-scoped surfaces provisioned by platform-infra. These helpers derive
  object names from the validated project code and never require shared-table
  DML grants for project roles.
#}

{% macro esf_domain_project_code(project_code) -%}
    {%- if project_code is not string or project_code | trim == '' -%}
        {{ exceptions.raise_compiler_error('project_code must be a non-empty string') }}
    {%- endif -%}
    {%- set normalized = project_code | trim | upper -%}
    {%- if modules.re.fullmatch('^[A-Z][A-Z0-9_]{1,31}$', normalized) is none -%}
        {{ exceptions.raise_compiler_error('project_code must match ^[A-Z][A-Z0-9_]{1,31}$') }}
    {%- endif -%}
    {{ return(normalized) }}
{%- endmacro %}

{% macro esf_domain_control_relation(project_code, object_name) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {%- set normalized_object = object_name | string | trim | upper -%}
    {%- set allowed_objects = [
        'PIPELINE_CHECKPOINT',
        'PIPELINE_RUN',
        'PIPELINE_CHECK_RESULT'
    ] -%}
    {%- if normalized_object not in allowed_objects -%}
        {{ exceptions.raise_compiler_error('unsupported domain control relation: ' ~ normalized_object) }}
    {%- endif -%}
    {{ return('PLATFORM_CONTROL.OPERATIONS.' ~ code ~ '_' ~ normalized_object) }}
{%- endmacro %}

{% macro esf_domain_control_procedure(project_code, procedure_name) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {%- set normalized_procedure = procedure_name | string | trim | upper -%}
    {%- set allowed_procedures = [
        'ADVANCE_PIPELINE_CHECKPOINT',
        'PIPELINE_RUN_START',
        'PIPELINE_RUN_FINISH',
        'RECORD_PIPELINE_CHECK_RESULT'
    ] -%}
    {%- if normalized_procedure not in allowed_procedures -%}
        {{ exceptions.raise_compiler_error('unsupported domain control procedure: ' ~ normalized_procedure) }}
    {%- endif -%}
    {{ return('PLATFORM_CONTROL.OPERATIONS.' ~ code ~ '_' ~ normalized_procedure) }}
{%- endmacro %}

{% macro esf_domain_checkpoint_read_sql(project_code, dataset_id, checkpoint_kind, control_relation=none) -%}
    {%- if control_relation is none -%}
        {%- set control_relation = enterprise_snowflake_framework.esf_domain_control_relation(
            project_code, 'PIPELINE_CHECKPOINT'
        ) -%}
    {%- endif -%}
    {{ enterprise_snowflake_framework.esf_checkpoint_read_sql(
        project_code,
        dataset_id,
        checkpoint_kind,
        control_relation
    ) }}
{%- endmacro %}

{% macro esf_domain_checkpoint_advance_call_sql(
    project_code,
    dataset_id,
    checkpoint_kind,
    checkpoint_value_sql,
    batch_id,
    git_sha,
    procedure_relation=none
) -%}
    {%- if checkpoint_kind not in ['watermark', 'cursor', 'source_position', 'event_offset', 'snapshot_id', 'file_identity'] -%}
        {{ exceptions.raise_compiler_error('unsupported checkpoint_kind: ' ~ checkpoint_kind) }}
    {%- endif -%}
    {%- if checkpoint_value_sql is not string or checkpoint_value_sql | trim == '' -%}
        {{ exceptions.raise_compiler_error('checkpoint_value_sql must be a non-empty SQL expression producing VARIANT') }}
    {%- endif -%}
    {%- if procedure_relation is none -%}
        {%- set procedure_relation = enterprise_snowflake_framework.esf_domain_control_procedure(
            project_code, 'ADVANCE_PIPELINE_CHECKPOINT'
        ) -%}
    {%- endif -%}
call {{ procedure_relation }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(checkpoint_kind | lower) }},
    {{ checkpoint_value_sql }},
    {{ enterprise_snowflake_framework.esf_sql_literal(batch_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha) }}
)
{%- endmacro %}

{% macro esf_domain_pipeline_run_start_call_sql(
    project_code,
    run_id,
    attempt_number,
    pipeline_id,
    dataset_id=none,
    git_sha=none,
    query_tag_expression='NULL',
    checkpoint_before_expression='NULL',
    procedure_relation=none
) -%}
    {%- if attempt_number | int < 1 -%}
        {{ exceptions.raise_compiler_error('attempt_number must be >= 1') }}
    {%- endif -%}
    {%- if procedure_relation is none -%}
        {%- set procedure_relation = enterprise_snowflake_framework.esf_domain_control_procedure(
            project_code, 'PIPELINE_RUN_START'
        ) -%}
    {%- endif -%}
call {{ procedure_relation }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(run_id) }},
    {{ attempt_number | int }},
    {{ enterprise_snowflake_framework.esf_sql_literal(pipeline_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha) }},
    {{ query_tag_expression }},
    {{ checkpoint_before_expression }}
)
{%- endmacro %}

{% macro esf_domain_pipeline_run_finish_call_sql(
    project_code,
    run_id,
    attempt_number,
    status,
    checkpoint_after_expression='NULL',
    rows_read_expression='NULL',
    rows_written_expression='NULL',
    rows_inserted_expression='NULL',
    rows_updated_expression='NULL',
    rows_deleted_expression='NULL',
    error_class=none,
    error_message=none,
    details_expression='NULL',
    procedure_relation=none
) -%}
    {%- set allowed_statuses = ['SUCCEEDED', 'FAILED', 'CANCELLED'] -%}
    {%- set normalized_status = status | upper -%}
    {%- if normalized_status not in allowed_statuses -%}
        {{ exceptions.raise_compiler_error('finish status must be one of: ' ~ (allowed_statuses | join(', '))) }}
    {%- endif -%}
    {%- if attempt_number | int < 1 -%}
        {{ exceptions.raise_compiler_error('attempt_number must be >= 1') }}
    {%- endif -%}
    {%- if procedure_relation is none -%}
        {%- set procedure_relation = enterprise_snowflake_framework.esf_domain_control_procedure(
            project_code, 'PIPELINE_RUN_FINISH'
        ) -%}
    {%- endif -%}
call {{ procedure_relation }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(run_id) }},
    {{ attempt_number | int }},
    {{ enterprise_snowflake_framework.esf_sql_literal(normalized_status) }},
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

{% macro esf_domain_record_check_result_sql(
    project_code,
    check_query,
    run_id,
    attempt_number,
    dataset_id,
    procedure_relation=none
) -%}
    {%- if attempt_number | int < 1 -%}
        {{ exceptions.raise_compiler_error('attempt_number must be >= 1') }}
    {%- endif -%}
    {%- if check_query is not string or check_query | trim == '' -%}
        {{ exceptions.raise_compiler_error('check_query must be a non-empty SQL query') }}
    {%- endif -%}
    {%- if procedure_relation is none -%}
        {%- set procedure_relation = enterprise_snowflake_framework.esf_domain_control_procedure(
            project_code, 'RECORD_PIPELINE_CHECK_RESULT'
        ) -%}
    {%- endif -%}
execute immediate $$
declare
    check_results resultset default (
        {{ check_query }}
    );
    check_cursor cursor for check_results;
begin
    for check_row in check_cursor do
        call {{ procedure_relation }}(
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
