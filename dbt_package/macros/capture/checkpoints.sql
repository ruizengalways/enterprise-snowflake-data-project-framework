{% macro esf_checkpoint_read_sql(project_code, dataset_id, checkpoint_kind, control_relation='PLATFORM_CONTROL.OPERATIONS.PIPELINE_CHECKPOINT') -%}
    {%- if project_code is not string or project_code | trim == '' -%}
        {{ exceptions.raise_compiler_error('project_code must be a non-empty string') }}
    {%- endif -%}
    {%- if dataset_id is not string or dataset_id | trim == '' -%}
        {{ exceptions.raise_compiler_error('dataset_id must be a non-empty string') }}
    {%- endif -%}
    {%- if checkpoint_kind not in ['watermark', 'cursor', 'source_position', 'event_offset', 'snapshot_id', 'file_identity'] -%}
        {{ exceptions.raise_compiler_error('unsupported checkpoint_kind: ' ~ checkpoint_kind) }}
    {%- endif -%}
select
    checkpoint_value,
    last_successful_batch_id,
    last_successful_at,
    last_git_sha,
    row_version
from {{ control_relation }}
where project_code = '{{ project_code | upper | replace("'", "''") }}'
  and dataset_id = '{{ dataset_id | lower | replace("'", "''") }}'
  and checkpoint_kind = '{{ checkpoint_kind | lower | replace("'", "''") }}'
{%- endmacro %}

{% macro esf_checkpoint_advance_call_sql(
    project_code,
    dataset_id,
    checkpoint_kind,
    checkpoint_value_sql,
    batch_id,
    git_sha,
    procedure_relation='PLATFORM_CONTROL.OPERATIONS.ADVANCE_PIPELINE_CHECKPOINT'
) -%}
    {%- if checkpoint_kind not in ['watermark', 'cursor', 'source_position', 'event_offset', 'snapshot_id', 'file_identity'] -%}
        {{ exceptions.raise_compiler_error('unsupported checkpoint_kind: ' ~ checkpoint_kind) }}
    {%- endif -%}
    {%- if checkpoint_value_sql is not string or checkpoint_value_sql | trim == '' -%}
        {{ exceptions.raise_compiler_error('checkpoint_value_sql must be a non-empty SQL expression producing VARIANT') }}
    {%- endif -%}
call {{ procedure_relation }}(
    '{{ project_code | upper | replace("'", "''") }}',
    '{{ dataset_id | lower | replace("'", "''") }}',
    '{{ checkpoint_kind | lower | replace("'", "''") }}',
    {{ checkpoint_value_sql }},
    '{{ batch_id | replace("'", "''") }}',
    '{{ git_sha | replace("'", "''") }}'
)
{%- endmacro %}
