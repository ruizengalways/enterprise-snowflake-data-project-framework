{#
  Full dataset reset helpers.

  RESET is deliberately separate from repair/replay. The framework owns only the
  bounded lifecycle calls and safe SQL assembly/execution. Domain repositories
  explicitly list reconstructable relations to clear; generic metadata never
  accepts arbitrary caller-controlled relation names.
#}

{% macro esf_domain_reset_relation(project_code, object_name) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {%- set normalized = object_name | string | trim | upper -%}
    {%- set allowed = ['DATASET_LIFECYCLE', 'DATASET_RESET'] -%}
    {%- if normalized not in allowed -%}
        {{ exceptions.raise_compiler_error('unsupported reset relation: ' ~ normalized) }}
    {%- endif -%}
    {{ return('PLATFORM_CONTROL.OPERATIONS.' ~ code ~ '_' ~ normalized) }}
{%- endmacro %}

{% macro esf_domain_reset_procedure(project_code, operation) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {%- set normalized = operation | string | trim | upper -%}
    {%- set allowed = ['DATASET_RESET_START', 'DATASET_RESET_COMPLETE'] -%}
    {%- if normalized not in allowed -%}
        {{ exceptions.raise_compiler_error('unsupported reset procedure: ' ~ normalized) }}
    {%- endif -%}
    {{ return('PLATFORM_CONTROL.OPERATIONS.' ~ code ~ '_' ~ normalized) }}
{%- endmacro %}

{% macro esf_domain_reset_read_sql(project_code, dataset_id) -%}
select *
from {{ enterprise_snowflake_framework.esf_domain_reset_relation(project_code, 'DATASET_RESET') }}
where dataset_id = {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }}
order by requested_at desc
{%- endmacro %}

{% macro esf_domain_lifecycle_read_sql(project_code, dataset_id) -%}
select *
from {{ enterprise_snowflake_framework.esf_domain_reset_relation(project_code, 'DATASET_LIFECYCLE') }}
where dataset_id = {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }}
{%- endmacro %}

{% macro esf_domain_reset_start_call_sql(
    project_code,
    reset_id,
    dataset_id,
    reason,
    git_sha=none,
    details_expression='NULL'
) -%}
call {{ enterprise_snowflake_framework.esf_domain_reset_procedure(project_code, 'DATASET_RESET_START') }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(reset_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(reason) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha) }},
    {{ details_expression }}
)
{%- endmacro %}

{% macro esf_domain_reset_complete_call_sql(
    project_code,
    reset_id,
    dataset_id,
    details_expression='NULL'
) -%}
call {{ enterprise_snowflake_framework.esf_domain_reset_procedure(project_code, 'DATASET_RESET_COMPLETE') }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(reset_id) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ details_expression }}
)
{%- endmacro %}

{% macro esf_reset_validate_relation(relation_name) -%}
    {%- if relation_name is not string or relation_name | trim == '' -%}
        {{ exceptions.raise_compiler_error('reset relation must be a non-empty string') }}
    {%- endif -%}
    {%- set normalized = relation_name | trim | upper -%}
    {%- if modules.re.fullmatch('^[A-Z][A-Z0-9_]{0,62}\\.[A-Z][A-Z0-9_]{0,62}\\.[A-Z][A-Z0-9_]{0,62}$', normalized) is none -%}
        {{ exceptions.raise_compiler_error('reset relation must be a fully-qualified unquoted DATABASE.SCHEMA.OBJECT name') }}
    {%- endif -%}
    {{ return(normalized) }}
{%- endmacro %}

{% macro esf_reset_validate_relations(relations) -%}
    {%- if relations is not sequence or relations is string or relations | length == 0 -%}
        {{ exceptions.raise_compiler_error('full reset requires a non-empty explicit relations list') }}
    {%- endif -%}
    {%- set validated = [] -%}
    {%- for relation in relations -%}
        {%- do validated.append(enterprise_snowflake_framework.esf_reset_validate_relation(relation)) -%}
    {%- endfor -%}
    {{ return(validated) }}
{%- endmacro %}

{% macro esf_dataset_full_reset_sql(
    project_code,
    reset_id,
    dataset_id,
    reason,
    relations,
    git_sha=none,
    details_expression='NULL'
) -%}
    {%- set validated_relations = enterprise_snowflake_framework.esf_reset_validate_relations(relations) -%}

{{ enterprise_snowflake_framework.esf_domain_reset_start_call_sql(
    project_code, reset_id, dataset_id, reason, git_sha, details_expression
) }};

{%- for relation in validated_relations %}
truncate table if exists {{ relation }};
{%- endfor %}

{{ enterprise_snowflake_framework.esf_domain_reset_complete_call_sql(
    project_code, reset_id, dataset_id, details_expression
) }};
{%- endmacro %}

{% macro esf_execute_dataset_full_reset(
    project_code,
    reset_id,
    dataset_id,
    reason,
    relations,
    git_sha=none,
    details_expression='NULL'
) -%}
    {%- if not execute -%}
        {{ exceptions.raise_compiler_error('esf_execute_dataset_full_reset must be invoked with dbt run-operation against Snowflake') }}
    {%- endif -%}
    {%- set validated_relations = enterprise_snowflake_framework.esf_reset_validate_relations(relations) -%}
    {%- set start_sql = enterprise_snowflake_framework.esf_domain_reset_start_call_sql(
        project_code, reset_id, dataset_id, reason, git_sha, details_expression
    ) -%}
    {%- do log('Starting full reset for ' ~ (dataset_id | lower) ~ ' with reset_id=' ~ reset_id, info=true) -%}
    {%- do run_query(start_sql) -%}

    {# Intentionally execute one TRUNCATE at a time. If any relation fails, the
       macro stops before RESET_COMPLETE and the lifecycle stays RESETTING. #}
    {%- for relation in validated_relations -%}
        {%- do log('Reset truncating ' ~ relation, info=true) -%}
        {%- do run_query('truncate table if exists ' ~ relation) -%}
    {%- endfor -%}

    {%- set complete_sql = enterprise_snowflake_framework.esf_domain_reset_complete_call_sql(
        project_code, reset_id, dataset_id, details_expression
    ) -%}
    {%- do run_query(complete_sql) -%}
    {%- do log('Reset is READY_FOR_INITIAL_LOAD for ' ~ (dataset_id | lower), info=true) -%}
    {{ return('reset ready for initial load') }}
{%- endmacro %}
