{% macro esf_dataset_metadata(dataset_id) -%}
    {%- set datasets = var('esf_datasets', {}) -%}
    {%- if dataset_id not in datasets -%}
        {{ exceptions.raise_compiler_error('dataset metadata not provided to dbt for: ' ~ dataset_id) }}
    {%- endif -%}
    {{ return(datasets[dataset_id]) }}
{%- endmacro %}

{% macro esf_apply_dataset_config(dataset_id) -%}
    {# Small technical config bridge only. Domain meaning stays in the model SELECT. #}
    {%- set dataset = enterprise_snowflake_framework.esf_dataset_metadata(dataset_id) -%}
    {%- set materialization = dataset.get('materialization', {}) -%}
    {%- set materialization_type = materialization.get('type') -%}
    {%- set runtime = dataset.get('runtime', {}) -%}
    {%- set runtime_mode = runtime.get('mode') -%}
    {%- set load = dataset.get('load') -%}
    {%- set strategy = load.get('strategy') if load else none -%}
    {%- set query_tag = dataset.get('query_tag') -%}

    {%- if query_tag -%}
        {%- do config(query_tag=query_tag) -%}
    {%- endif -%}
    {%- if materialization_type == 'custom' or runtime_mode in ['external', 'custom'] -%}
        {{ return('') }}
    {%- endif -%}
    {%- if materialization_type == 'view' -%}
        {%- do config(materialized='view') -%}
        {{ return('') }}
    {%- endif -%}
    {%- if materialization_type == 'dynamic_table' -%}
        {%- if runtime_mode != 'snowflake_managed' -%}
            {{ exceptions.raise_compiler_error('dynamic_table requires runtime.mode=snowflake_managed: ' ~ dataset_id) }}
        {%- endif -%}
        {%- do config(materialized='dynamic_table', target_lag=materialization.get('target_lag'), refresh_mode=materialization.get('refresh_mode', 'adaptive') | upper, snowflake_warehouse=target.warehouse) -%}
        {{ return('') }}
    {%- endif -%}
    {%- if materialization_type == 'snapshot' -%}
        {{ exceptions.raise_compiler_error('snapshot is a dbt snapshot resource; define it explicitly: ' ~ dataset_id) }}
    {%- endif -%}
    {%- if materialization_type != 'table' -%}
        {{ exceptions.raise_compiler_error('unsupported materialization.type for dataset ' ~ dataset_id ~ ': ' ~ materialization_type) }}
    {%- endif -%}

    {%- if strategy == 'append_only' -%}
        {%- do config(materialized='incremental', incremental_strategy='append') -%}
    {%- elif strategy == 'incremental_merge' -%}
        {%- set keys = load.get('business_key', []) -%}
        {%- set unique_key = keys[0] if keys | length == 1 else keys -%}
        {%- do config(materialized='incremental', incremental_strategy='merge', unique_key=unique_key) -%}
    {%- elif strategy == 'scd1' -%}
        {%- do config(materialized='esf_scd1_current', esf_dataset_id=dataset_id) -%}
    {%- elif strategy == 'scd2' -%}
        {%- do config(materialized='esf_scd2_history', esf_dataset_id=dataset_id) -%}
    {%- else -%}
        {%- do config(materialized='table') -%}
    {%- endif -%}
    {{ return('') }}
{%- endmacro %}
