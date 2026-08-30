{% macro esf_scd2_dataset_metadata(dataset_id) -%}
    {%- set dataset = enterprise_snowflake_framework.esf_dataset_metadata(dataset_id) -%}
    {%- set strategy = dataset.get('load_strategy') -%}
    {%- if strategy not in ['scd2_snapshot', 'scd2_merge', 'scd2_stream_task'] -%}
        {{ exceptions.raise_compiler_error(
            'dataset ' ~ dataset_id ~ ' is not configured with an SCD2 load strategy'
        ) }}
    {%- endif -%}

    {%- set scd2 = dataset.get('scd2') -%}
    {%- if not scd2 -%}
        {{ exceptions.raise_compiler_error('SCD2 metadata not provided to dbt for dataset: ' ~ dataset_id) }}
    {%- endif -%}

    {{ return(scd2) }}
{%- endmacro %}

{% macro esf_scd2_require_strategy(dataset_id, allowed_strategies) -%}
    {%- set dataset = enterprise_snowflake_framework.esf_dataset_metadata(dataset_id) -%}
    {%- set strategy = dataset.get('load_strategy') -%}
    {%- if strategy not in allowed_strategies -%}
        {{ exceptions.raise_compiler_error(
            'dataset ' ~ dataset_id ~ ' uses ' ~ strategy ~ '; expected one of: ' ~ (allowed_strategies | join(', '))
        ) }}
    {%- endif -%}
    {{ return(dataset) }}
{%- endmacro %}

{% macro esf_scd2_hash_expression(column_names, relation_alias=none) -%}
    {%- set columns = enterprise_snowflake_framework.esf_require_columns(column_names, 'tracked_columns') -%}
hash(
    {%- for column in columns %}
    {%- if relation_alias %}{{ relation_alias }}.{% endif %}{{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
    {%- endfor %}
)
{%- endmacro %}

{% macro esf_scd2_enriched_relation(source_relation, dataset_id) -%}
    {%- set scd2 = enterprise_snowflake_framework.esf_scd2_dataset_metadata(dataset_id) -%}
(
    select
        source_rows.*,
        {{ enterprise_snowflake_framework.esf_scd2_hash_expression(
            scd2.get('tracked_columns', []),
            'source_rows'
        ) }} as _esf_record_hash
    from {{ source_relation }} as source_rows
)
{%- endmacro %}

{% macro esf_scd2_history_select_for_dataset(event_relation, dataset_id) -%}
    {%- set dataset = enterprise_snowflake_framework.esf_scd2_require_strategy(
        dataset_id,
        ['scd2_merge', 'scd2_stream_task']
    ) -%}
    {%- set scd2 = enterprise_snowflake_framework.esf_scd2_dataset_metadata(dataset_id) -%}
    {%- set enriched_relation = enterprise_snowflake_framework.esf_scd2_enriched_relation(
        event_relation,
        dataset_id
    ) -%}
{{ enterprise_snowflake_framework.esf_scd2_event_history_select(
    enriched_relation,
    dataset.get('business_key', []),
    scd2.get('effective_at_column'),
    scd2.get('order_columns', []),
    '_esf_record_hash',
    scd2.get('operation_column'),
    scd2.get('delete_values', [])
) }}
{%- endmacro %}

{% macro esf_scd2_rebuild_affected_keys_for_dataset_sql(
    target_relation,
    event_relation,
    affected_keys_relation,
    dataset_id
) -%}
    {%- set dataset = enterprise_snowflake_framework.esf_scd2_require_strategy(
        dataset_id,
        ['scd2_merge', 'scd2_stream_task']
    ) -%}
    {%- set scd2 = enterprise_snowflake_framework.esf_scd2_dataset_metadata(dataset_id) -%}
    {%- if scd2.get('late_arriving_policy') != 'rebuild_affected_keys' -%}
        {{ exceptions.raise_compiler_error(
            'dataset ' ~ dataset_id ~ ' does not allow affected-key rebuild for late-arriving events'
        ) }}
    {%- endif -%}
    {%- set enriched_relation = enterprise_snowflake_framework.esf_scd2_enriched_relation(
        event_relation,
        dataset_id
    ) -%}
{{ enterprise_snowflake_framework.esf_scd2_rebuild_affected_keys_sql(
    target_relation,
    enriched_relation,
    affected_keys_relation,
    dataset.get('business_key', []),
    scd2.get('effective_at_column'),
    scd2.get('order_columns', []),
    '_esf_record_hash',
    scd2.get('operation_column'),
    scd2.get('delete_values', [])
) }}
{%- endmacro %}

{% macro esf_scd2_snapshot_apply_for_dataset_sql(
    target_relation,
    snapshot_relation,
    dataset_id,
    effective_at_expression='current_timestamp()'
) -%}
    {%- set dataset = enterprise_snowflake_framework.esf_scd2_require_strategy(
        dataset_id,
        ['scd2_snapshot']
    ) -%}
    {%- set enriched_relation = enterprise_snowflake_framework.esf_scd2_enriched_relation(
        snapshot_relation,
        dataset_id
    ) -%}
{{ enterprise_snowflake_framework.esf_scd2_snapshot_apply_sql(
    target_relation,
    enriched_relation,
    dataset.get('business_key', []),
    '_esf_record_hash',
    effective_at_expression
) }}
{%- endmacro %}
