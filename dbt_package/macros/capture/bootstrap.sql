{#
  Safe initial snapshot -> incremental/CDC handoff helpers.

  Source extraction remains source-specific. These macros only target the
  domain-scoped PLATFORM_CONTROL bootstrap state machine and use metadata to
  preserve the handoff contract.
#}

{% macro esf_bootstrap_metadata(dataset_id) -%}
    {%- set dataset = enterprise_snowflake_framework.esf_dataset_metadata(dataset_id) -%}
    {%- set capture = dataset.get('capture') -%}
    {%- if not capture -%}
        {{ exceptions.raise_compiler_error('capture metadata not provided to dbt for dataset: ' ~ dataset_id) }}
    {%- endif -%}
    {%- set bootstrap = capture.get('bootstrap') -%}
    {%- if not bootstrap -%}
        {{ exceptions.raise_compiler_error('bootstrap metadata not provided to dbt for dataset: ' ~ dataset_id) }}
    {%- endif -%}
    {{ return({'capture': capture, 'bootstrap': bootstrap}) }}
{%- endmacro %}

{% macro esf_domain_bootstrap_relation(project_code) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {{ return('PLATFORM_CONTROL.OPERATIONS.' ~ code ~ '_PIPELINE_BOOTSTRAP') }}
{%- endmacro %}

{% macro esf_domain_bootstrap_procedure(project_code, operation) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {%- set normalized = operation | string | trim | upper -%}
    {%- set allowed = [
        'PIPELINE_BOOTSTRAP_START',
        'PIPELINE_BOOTSTRAP_MARK_SNAPSHOT_LANDED',
        'PIPELINE_BOOTSTRAP_MARK_VALIDATED',
        'PIPELINE_BOOTSTRAP_COMMIT_HANDOFF'
    ] -%}
    {%- if normalized not in allowed -%}
        {{ exceptions.raise_compiler_error('unsupported bootstrap operation: ' ~ normalized) }}
    {%- endif -%}
    {{ return('PLATFORM_CONTROL.OPERATIONS.' ~ code ~ '_' ~ normalized) }}
{%- endmacro %}

{% macro esf_domain_bootstrap_read_sql(project_code, dataset_id, bootstrap_id=none) -%}
select
    dataset_id,
    bootstrap_id,
    status,
    handoff_checkpoint_kind,
    handoff_position,
    incremental_start,
    snapshot_id,
    snapshot_batch_id,
    reconciliation_details,
    git_sha,
    boundary_captured_at,
    snapshot_landed_at,
    snapshot_validated_at,
    handoff_committed_at,
    updated_at
from {{ enterprise_snowflake_framework.esf_domain_bootstrap_relation(project_code) }}
where dataset_id = {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }}
{%- if bootstrap_id is not none %}
  and bootstrap_id = {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap_id) }}
{%- endif %}
order by boundary_captured_at desc
{%- endmacro %}

{% macro esf_domain_bootstrap_start_call_sql(
    project_code,
    dataset_id,
    bootstrap_id,
    handoff_position_expression,
    git_sha
) -%}
    {%- set metadata = enterprise_snowflake_framework.esf_bootstrap_metadata(dataset_id) -%}
    {%- set capture = metadata.get('capture') -%}
    {%- set bootstrap = metadata.get('bootstrap') -%}
    {%- set procedure = enterprise_snowflake_framework.esf_domain_bootstrap_procedure(
        project_code, 'PIPELINE_BOOTSTRAP_START'
    ) -%}
call {{ procedure }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(capture.get('checkpoint_kind')) }},
    {{ handoff_position_expression }},
    {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap.get('incremental_start')) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha) }}
)
{%- endmacro %}

{% macro esf_domain_bootstrap_snapshot_landed_call_sql(
    project_code,
    dataset_id,
    bootstrap_id,
    snapshot_id,
    snapshot_batch_id
) -%}
call {{ enterprise_snowflake_framework.esf_domain_bootstrap_procedure(
    project_code, 'PIPELINE_BOOTSTRAP_MARK_SNAPSHOT_LANDED'
) }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(snapshot_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(snapshot_batch_id) }}
)
{%- endmacro %}

{% macro esf_domain_bootstrap_validated_call_sql(
    project_code,
    dataset_id,
    bootstrap_id,
    reconciliation_details_expression
) -%}
call {{ enterprise_snowflake_framework.esf_domain_bootstrap_procedure(
    project_code, 'PIPELINE_BOOTSTRAP_MARK_VALIDATED'
) }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap_id) }},
    {{ reconciliation_details_expression }}
)
{%- endmacro %}

{% macro esf_domain_bootstrap_commit_handoff_call_sql(
    project_code,
    dataset_id,
    bootstrap_id,
    batch_id,
    git_sha
) -%}
call {{ enterprise_snowflake_framework.esf_domain_bootstrap_procedure(
    project_code, 'PIPELINE_BOOTSTRAP_COMMIT_HANDOFF'
) }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(batch_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha) }}
)
{%- endmacro %}
