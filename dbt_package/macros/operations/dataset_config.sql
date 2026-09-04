{#
  Dataset configuration remains Git-owned. These helpers only render access to
  the platform-provisioned, domain-scoped audit snapshot surface.
#}

{% macro esf_dataset_config_snapshot(dataset_id) -%}
    {%- set snapshots = var('esf_dataset_snapshots', {}) -%}
    {%- if dataset_id not in snapshots -%}
        {{ exceptions.raise_compiler_error('dataset config snapshot not provided to dbt for: ' ~ dataset_id) }}
    {%- endif -%}
    {{ return(snapshots[dataset_id]) }}
{%- endmacro %}

{% macro esf_domain_dataset_config_relation(project_code) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {{ return('PLATFORM_CONTROL.CONFIG.' ~ code ~ '_DATASET_CONFIG_SNAPSHOT') }}
{%- endmacro %}

{% macro esf_domain_dataset_config_procedure(project_code) -%}
    {%- set code = enterprise_snowflake_framework.esf_domain_project_code(project_code) -%}
    {{ return('PLATFORM_CONTROL.CONFIG.' ~ code ~ '_REGISTER_DATASET_CONFIG_SNAPSHOT') }}
{%- endmacro %}

{% macro esf_domain_dataset_config_read_sql(project_code, dataset_id, control_relation=none) -%}
    {%- if control_relation is none -%}
        {%- set control_relation = enterprise_snowflake_framework.esf_domain_dataset_config_relation(project_code) -%}
    {%- endif -%}
select
    dataset_id,
    config_schema_version,
    git_sha,
    config_hash,
    config,
    deployed_at,
    deployed_by
from {{ control_relation }}
where dataset_id = {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }}
order by deployed_at desc
{%- endmacro %}

{% macro esf_domain_register_dataset_config_call_sql(
    project_code,
    dataset_id,
    git_sha,
    procedure_relation=none
) -%}
    {%- if git_sha is not string or git_sha | trim == '' -%}
        {{ exceptions.raise_compiler_error('git_sha must be a non-empty string') }}
    {%- endif -%}
    {%- set snapshot = enterprise_snowflake_framework.esf_dataset_config_snapshot(dataset_id) -%}
    {%- if procedure_relation is none -%}
        {%- set procedure_relation = enterprise_snowflake_framework.esf_domain_dataset_config_procedure(project_code) -%}
    {%- endif -%}
call {{ procedure_relation }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ snapshot['config_schema_version'] | int }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha | trim) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(snapshot['config_hash']) }},
    parse_json({{ enterprise_snowflake_framework.esf_sql_literal(snapshot['config_json']) }})
)
{%- endmacro %}
