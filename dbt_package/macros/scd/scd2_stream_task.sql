{% macro esf_scd2_affected_keys_table_sql(
    affected_keys_relation,
    event_relation,
    key_columns
) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
create transient table if not exists {{ affected_keys_relation }} as
select distinct
    {%- for key in keys %}
    {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
    {%- endfor %}
from {{ event_relation }}
where 1 = 0
{%- endmacro %}

{% macro esf_scd2_stream_task_body_sql(
    stream_relation,
    affected_keys_relation,
    target_relation,
    event_relation,
    key_columns,
    effective_at_column,
    order_columns,
    hash_column,
    operation_column=none,
    delete_values=[]
) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
begin
    begin transaction;

    insert overwrite into {{ affected_keys_relation }}
    select distinct
        {%- for key in keys %}
        {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
        {%- endfor %}
    from {{ stream_relation }};

    delete from {{ target_relation }} as target
    using {{ affected_keys_relation }} as affected
    where {{ enterprise_snowflake_framework.esf_equal_keys('target', 'affected', keys) }};

    insert into {{ target_relation }}
    {{ enterprise_snowflake_framework.esf_scd2_event_history_select(
        event_relation,
        keys,
        effective_at_column,
        order_columns,
        hash_column,
        operation_column,
        delete_values,
        affected_keys_relation
    ) }};

    commit;
exception
    when other then
        rollback;
        raise;
end
{%- endmacro %}

{% macro esf_scd2_stream_task_sql(
    task_relation,
    stream_relation,
    affected_keys_relation,
    target_relation,
    event_relation,
    warehouse,
    key_columns,
    effective_at_column,
    order_columns,
    hash_column,
    operation_column=none,
    delete_values=[],
    minimum_trigger_interval_seconds=30,
    timeout_ms=3600000,
    auto_retry_attempts=1,
    suspend_after_failures=3,
    comment=none,
    resume=true
) -%}
    {%- set body_sql -%}
{{ enterprise_snowflake_framework.esf_scd2_stream_task_body_sql(
    stream_relation,
    affected_keys_relation,
    target_relation,
    event_relation,
    key_columns,
    effective_at_column,
    order_columns,
    hash_column,
    operation_column,
    delete_values
) }}
    {%- endset -%}
{{ enterprise_snowflake_framework.esf_triggered_task_sql(
    task_relation,
    stream_relation,
    warehouse,
    body_sql,
    minimum_trigger_interval_seconds,
    timeout_ms,
    auto_retry_attempts,
    suspend_after_failures,
    'NO_OVERLAP',
    comment,
    resume
) }}
{%- endmacro %}
