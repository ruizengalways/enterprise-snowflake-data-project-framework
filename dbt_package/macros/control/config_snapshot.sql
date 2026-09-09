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

{% macro esf_domain_dataset_config_read_sql(project_code, dataset_id) -%}
select dataset_id, config_schema_version, git_sha, config_hash, config, deployed_at, deployed_by
from {{ enterprise_snowflake_framework.esf_domain_dataset_config_relation(project_code) }}
where dataset_id = {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }}
order by deployed_at desc
{%- endmacro %}

{% macro esf_domain_register_dataset_config_call_sql(project_code, dataset_id, git_sha) -%}
    {%- set snapshot = enterprise_snowflake_framework.esf_dataset_config_snapshot(dataset_id) -%}
call {{ enterprise_snowflake_framework.esf_domain_dataset_config_procedure(project_code) }}(
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id | lower) }},
    {{ snapshot['config_schema_version'] | int }},
    {{ enterprise_snowflake_framework.esf_sql_literal(git_sha | trim) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(snapshot['config_hash']) }},
    parse_json({{ enterprise_snowflake_framework.esf_sql_literal(snapshot['config_json']) }})
)
{%- endmacro %}

{% macro esf_register_all_dataset_config_snapshots(project_code, git_sha) -%}
    {%- set snapshots = var('esf_dataset_snapshots', {}) -%}
    {%- for dataset_id in snapshots.keys() | sort -%}
        {%- if execute -%}
            {%- do run_query(enterprise_snowflake_framework.esf_domain_register_dataset_config_call_sql(project_code, dataset_id, git_sha)) -%}
        {%- endif -%}
    {%- endfor -%}
    {{ return(snapshots | length) }}
{%- endmacro %}
