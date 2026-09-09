{# Bootstrap tracks the boundary between already-landed Bronze data and downstream processing. #}

{% macro esf_domain_bootstrap_relation(project_code) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {{ return('PLATFORM_CONTROL.OPERATIONS.' ~ code ~ '_PIPELINE_BOOTSTRAP') }}
{%- endmacro %}

{% macro esf_domain_bootstrap_procedure(project_code, operation) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {%- set operation = operation | trim | upper -%}
    {%- if operation not in ['PIPELINE_BOOTSTRAP_START', 'PIPELINE_BOOTSTRAP_MARK_SNAPSHOT_LANDED', 'PIPELINE_BOOTSTRAP_MARK_VALIDATED', 'PIPELINE_BOOTSTRAP_COMMIT_HANDOFF'] -%}
        {{ exceptions.raise_compiler_error('unsupported bootstrap operation: ' ~ operation) }}
    {%- endif -%}
    {{ return('PLATFORM_CONTROL.OPERATIONS.' ~ code ~ '_' ~ operation) }}
{%- endmacro %}

{% macro esf_domain_bootstrap_read_sql(project_code, dataset_id, bootstrap_id=none) -%}
select *
from {{ enterprise_snowflake_framework.esf_domain_bootstrap_relation(project_code) }}
where dataset_id = {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }}
{%- if bootstrap_id is not none %}
  and bootstrap_id = {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap_id) }}
{%- endif %}
order by boundary_captured_at desc
{%- endmacro %}

{% macro esf_domain_bootstrap_start_call_sql(project_code, dataset_id, bootstrap_id, processing_checkpoint_kind, landed_boundary_expression, git_sha, incremental_start='exclusive') -%}
    {%- set kind = enterprise_snowflake_framework.esf_processing_checkpoint_kind(processing_checkpoint_kind) -%}
    {%- if incremental_start not in ['exclusive', 'inclusive'] -%}
        {{ exceptions.raise_compiler_error('incremental_start must be exclusive or inclusive') }}
    {%- endif -%}
call {{ enterprise_snowflake_framework.esf_domain_bootstrap_procedure(project_code, 'PIPELINE_BOOTSTRAP_START') }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(kind) }},
    {{ landed_boundary_expression }},
    {{ enterprise_snowflake_framework.esf_sql_literal(incremental_start) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha) }}
)
{%- endmacro %}

{% macro esf_domain_bootstrap_snapshot_landed_call_sql(project_code, dataset_id, bootstrap_id, snapshot_id, snapshot_batch_id) -%}
call {{ enterprise_snowflake_framework.esf_domain_bootstrap_procedure(project_code, 'PIPELINE_BOOTSTRAP_MARK_SNAPSHOT_LANDED') }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(snapshot_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(snapshot_batch_id) }}
)
{%- endmacro %}

{% macro esf_domain_bootstrap_validated_call_sql(project_code, dataset_id, bootstrap_id, reconciliation_passed_expression, reconciliation_details_expression) -%}
call {{ enterprise_snowflake_framework.esf_domain_bootstrap_procedure(project_code, 'PIPELINE_BOOTSTRAP_MARK_VALIDATED') }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap_id) }},
    {{ reconciliation_passed_expression }},
    {{ reconciliation_details_expression }}
)
{%- endmacro %}

{% macro esf_domain_bootstrap_commit_handoff_call_sql(project_code, dataset_id, bootstrap_id, batch_id, git_sha) -%}
call {{ enterprise_snowflake_framework.esf_domain_bootstrap_procedure(project_code, 'PIPELINE_BOOTSTRAP_COMMIT_HANDOFF') }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(bootstrap_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(batch_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha) }}
)
{%- endmacro %}
