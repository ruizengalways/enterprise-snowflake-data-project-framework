{% macro esf_sql_literal(value) -%}
    {%- if value is none -%}
        NULL
    {%- else -%}
        '{{ value | string | replace("'", "''") }}'
    {%- endif -%}
{%- endmacro %}

{% macro esf_pipeline_run_start_sql(
    run_relation,
    run_id,
    attempt_number,
    project_code,
    environment,
    pipeline_id,
    dataset_id=none,
    git_sha=none,
    query_tag_expression='NULL',
    checkpoint_before_expression='NULL'
) -%}
    {%- if attempt_number | int < 1 -%}
        {{ exceptions.raise_compiler_error('attempt_number must be >= 1') }}
    {%- endif -%}
merge into {{ run_relation }} as target
using (
    select
        {{ enterprise_snowflake_framework.esf_sql_literal(run_id) }} as run_id,
        {{ attempt_number | int }} as attempt_number,
        {{ enterprise_snowflake_framework.esf_sql_literal(project_code) }} as project_code,
        {{ enterprise_snowflake_framework.esf_sql_literal(environment) }} as environment,
        {{ enterprise_snowflake_framework.esf_sql_literal(pipeline_id) }} as pipeline_id,
        {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id) }} as dataset_id,
        'RUNNING' as status,
        current_timestamp() as started_at,
        {{ enterprise_snowflake_framework.esf_sql_literal(git_sha) }} as git_sha,
        {{ query_tag_expression }} as query_tag,
        {{ checkpoint_before_expression }} as checkpoint_before
) as source
    on target.run_id = source.run_id
   and target.attempt_number = source.attempt_number
when matched then update set
    project_code = source.project_code,
    environment = source.environment,
    pipeline_id = source.pipeline_id,
    dataset_id = source.dataset_id,
    status = source.status,
    started_at = source.started_at,
    finished_at = null,
    git_sha = source.git_sha,
    query_tag = source.query_tag,
    checkpoint_before = source.checkpoint_before,
    checkpoint_after = null,
    error_class = null,
    error_message = null,
    updated_at = current_timestamp(),
    updated_by = current_user()
when not matched then insert (
    run_id,
    attempt_number,
    project_code,
    environment,
    pipeline_id,
    dataset_id,
    status,
    started_at,
    git_sha,
    query_tag,
    checkpoint_before
) values (
    source.run_id,
    source.attempt_number,
    source.project_code,
    source.environment,
    source.pipeline_id,
    source.dataset_id,
    source.status,
    source.started_at,
    source.git_sha,
    source.query_tag,
    source.checkpoint_before
)
{%- endmacro %}

{% macro esf_pipeline_run_finish_sql(
    run_relation,
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
    details_expression='NULL'
) -%}
    {%- set allowed_statuses = ['SUCCEEDED', 'FAILED', 'CANCELLED'] -%}
    {%- set normalized_status = status | upper -%}
    {%- if normalized_status not in allowed_statuses -%}
        {{ exceptions.raise_compiler_error('finish status must be one of: ' ~ (allowed_statuses | join(', '))) }}
    {%- endif -%}
update {{ run_relation }}
set
    status = '{{ normalized_status }}',
    finished_at = current_timestamp(),
    checkpoint_after = {{ checkpoint_after_expression }},
    rows_read = {{ rows_read_expression }},
    rows_written = {{ rows_written_expression }},
    rows_inserted = {{ rows_inserted_expression }},
    rows_updated = {{ rows_updated_expression }},
    rows_deleted = {{ rows_deleted_expression }},
    error_class = {{ enterprise_snowflake_framework.esf_sql_literal(error_class) }},
    error_message = {{ enterprise_snowflake_framework.esf_sql_literal(error_message) }},
    details = {{ details_expression }},
    updated_at = current_timestamp(),
    updated_by = current_user()
where run_id = {{ enterprise_snowflake_framework.esf_sql_literal(run_id) }}
  and attempt_number = {{ attempt_number | int }}
{%- endmacro %}
