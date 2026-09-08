{% macro esf_dataset_metadata(dataset_id) -%}
    {%- set datasets = var('esf_datasets', {}) -%}
    {%- if dataset_id not in datasets -%}
        {{ exceptions.raise_compiler_error('dataset metadata not provided to dbt for: ' ~ dataset_id) }}
    {%- endif -%}
    {{ return(datasets[dataset_id]) }}
{%- endmacro %}

{% macro esf_dataset_load(dataset_id) -%}
    {%- set dataset = enterprise_snowflake_framework.esf_dataset_metadata(dataset_id) -%}
    {%- if dataset.get('load') -%}
        {{ return(dataset.get('load')) }}
    {%- endif -%}

    {# Backward-compatible projection for callers that construct old dbt vars directly. #}
    {%- set legacy = dataset.get('load_strategy') -%}
    {%- set strategy_map = {
        'full_refresh': ['full_refresh', 'dbt_batch'],
        'append_only': ['append_only', 'dbt_batch'],
        'incremental_merge': ['incremental_merge', 'dbt_batch'],
        'scd1_merge': ['scd1', 'dbt_batch'],
        'scd2_snapshot': ['scd2', 'dbt_snapshot'],
        'scd2_merge': ['scd2', 'dbt_batch'],
        'scd2_stream_task': ['scd2', 'stream_task']
    } -%}
    {%- if legacy not in strategy_map -%}
        {{ exceptions.raise_compiler_error('unsupported legacy load_strategy for dataset ' ~ dataset_id ~ ': ' ~ legacy) }}
    {%- endif -%}
    {%- set mapped = strategy_map[legacy] -%}
    {%- set mode = 'custom' if dataset.get('implementation', 'standard') == 'custom' else mapped[1] -%}
    {%- set load = {
        'strategy': mapped[0],
        'execution': {'mode': mode}
    } -%}
    {%- if dataset.get('business_key') -%}
        {%- do load.update({'business_key': dataset.get('business_key')}) -%}
    {%- endif -%}
    {%- if dataset.get('watermark_column') -%}
        {%- do load.update({'watermark_column': dataset.get('watermark_column')}) -%}
    {%- endif -%}
    {%- if dataset.get('scd2') -%}
        {%- do load.update({'scd2': dataset.get('scd2')}) -%}
    {%- endif -%}
    {{ return(load) }}
{%- endmacro %}

{% macro esf_apply_dataset_config(dataset_id) -%}
    {#
      Metadata controls HOW the model is maintained. The model body remains
      normal domain SQL and controls WHAT the data means.

      This macro deliberately configures dbt/Snowflake materialization only;
      it does not generate joins, filters, CASE expressions, aggregations, or
      other business transformations.
    #}
    {%- set dataset = enterprise_snowflake_framework.esf_dataset_metadata(dataset_id) -%}
    {%- set load = enterprise_snowflake_framework.esf_dataset_load(dataset_id) -%}
    {%- set strategy = load.get('strategy') -%}
    {%- set execution = load.get('execution', {}) -%}
    {%- set mode = execution.get('mode', 'dbt_batch') -%}
    {%- set query_tag = dataset.get('query_tag') -%}

    {%- if query_tag -%}
        {%- do config(query_tag=query_tag) -%}
    {%- endif -%}

    {%- if mode == 'custom' -%}
        {{ log('dataset ' ~ dataset_id ~ ' uses custom execution; framework leaves model materialization explicit', info=true) }}
        {{ return('') }}
    {%- endif -%}

    {%- if mode == 'dynamic_table' -%}
        {%- if strategy not in ['full_refresh', 'scd1'] -%}
            {{ exceptions.raise_compiler_error(
                'dynamic_table execution is supported only for full_refresh/current-result or scd1 semantics; dataset: ' ~ dataset_id
            ) }}
        {%- endif -%}
        {%- set target_lag = execution.get('target_lag') -%}
        {%- if not target_lag -%}
            {{ exceptions.raise_compiler_error('dynamic_table execution requires load.execution.target_lag for dataset: ' ~ dataset_id) }}
        {%- endif -%}
        {%- do config(
            materialized='dynamic_table',
            target_lag=target_lag,
            snowflake_warehouse=target.warehouse
        ) -%}
        {{ return('') }}
    {%- endif -%}

    {%- if mode == 'dbt_snapshot' -%}
        {{ exceptions.raise_compiler_error(
            'dbt_snapshot is an execution resource, not a model materialization; keep the readable SELECT in staging and define the snapshot explicitly for dataset: ' ~ dataset_id
        ) }}
    {%- endif -%}

    {%- if mode == 'stream_task' -%}
        {{ exceptions.raise_compiler_error(
            'stream_task execution is deployed as Snowflake stream/task primitives, not as a dbt model materialization; dataset: ' ~ dataset_id
        ) }}
    {%- endif -%}

    {%- if mode != 'dbt_batch' -%}
        {{ exceptions.raise_compiler_error('unsupported execution.mode for dataset ' ~ dataset_id ~ ': ' ~ mode) }}
    {%- endif -%}

    {%- if strategy == 'full_refresh' -%}
        {%- do config(materialized='table') -%}
    {%- elif strategy == 'append_only' -%}
        {%- do config(materialized='incremental', incremental_strategy='append') -%}
    {%- elif strategy in ['incremental_merge', 'scd1'] -%}
        {%- set keys = load.get('business_key', []) -%}
        {%- if not keys -%}
            {{ exceptions.raise_compiler_error(strategy ~ ' requires load.business_key for dataset: ' ~ dataset_id) }}
        {%- endif -%}
        {%- set unique_key = keys[0] if keys | length == 1 else keys -%}
        {%- do config(materialized='incremental', incremental_strategy='merge', unique_key=unique_key) -%}
    {%- elif strategy == 'scd2' -%}
        {{ exceptions.raise_compiler_error(
            'SCD2 history maintenance is a multi-statement technical primitive. Keep domain transformation SQL readable in staging/canonical input models and invoke the dedicated SCD2 execution primitive for dataset: ' ~ dataset_id
        ) }}
    {%- else -%}
        {{ exceptions.raise_compiler_error('unsupported load.strategy for dataset ' ~ dataset_id ~ ': ' ~ strategy) }}
    {%- endif -%}

    {{ return('') }}
{%- endmacro %}

{% macro esf_configure_dataset(dataset_id) -%}
    {# Deprecated compatibility alias. New projects should call esf_apply_dataset_config. #}
    {{ return(enterprise_snowflake_framework.esf_apply_dataset_config(dataset_id)) }}
{%- endmacro %}
