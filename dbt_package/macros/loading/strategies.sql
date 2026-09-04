{% macro esf_dataset_metadata(dataset_id) -%}
    {%- set datasets = var('esf_datasets', {}) -%}
    {%- if dataset_id not in datasets -%}
        {{ exceptions.raise_compiler_error("dataset metadata not provided to dbt for: " ~ dataset_id) }}
    {%- endif -%}
    {{ return(datasets[dataset_id]) }}
{%- endmacro %}

{% macro esf_configure_dataset(dataset_id) -%}
    {%- set dataset = enterprise_snowflake_framework.esf_dataset_metadata(dataset_id) -%}
    {%- set strategy = dataset.get('load_strategy') -%}
    {%- set query_tag = dataset.get('query_tag') -%}

    {%- if query_tag -%}
        {%- do config(query_tag=query_tag) -%}
    {%- endif -%}

    {%- if dataset.get('implementation', 'standard') == 'custom' -%}
        {{ exceptions.raise_compiler_error(
            "dataset " ~ dataset_id ~ " declares implementation=custom; configure its dbt materialization explicitly in project code"
        ) }}
    {%- endif -%}

    {%- if strategy == 'full_refresh' -%}
        {%- do config(materialized='table') -%}
    {%- elif strategy == 'append_only' -%}
        {%- do config(materialized='incremental', incremental_strategy='append') -%}
    {%- elif strategy in ['incremental_merge', 'scd1_merge'] -%}
        {%- set keys = dataset.get('business_key', []) -%}
        {%- if not keys -%}
            {{ exceptions.raise_compiler_error(strategy ~ " requires business_key metadata for dataset: " ~ dataset_id) }}
        {%- endif -%}
        {%- set unique_key = keys[0] if keys | length == 1 else keys -%}
        {%- do config(materialized='incremental', incremental_strategy='merge', unique_key=unique_key) -%}
    {%- elif strategy in ['scd2_snapshot', 'scd2_merge', 'scd2_stream_task'] -%}
        {{ exceptions.raise_compiler_error(
            "SCD2 strategy " ~ strategy ~ " is approved but not implemented by the basic-load macro yet; use the dedicated SCD2 framework implementation when added"
        ) }}
    {%- else -%}
        {{ exceptions.raise_compiler_error("unsupported load strategy for dataset " ~ dataset_id ~ ": " ~ strategy) }}
    {%- endif -%}

    {{ return('') }}
{%- endmacro %}
