{% macro esf_scd2_stream_task_body_sql(
    stream_relation,
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
    {%- set affected_key_query -%}
select distinct
    {%- for key in keys %}
    {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
    {%- endfor %}
from {{ stream_relation }}
    {%- endset -%}
begin
    begin transaction;

    -- Snowflake Streams provide repeatable-read semantics inside this explicit
    -- transaction, so both DML statements see the same change set. No shared
    -- affected-key work table or framework Stream checkpoint is required.
    delete from {{ target_relation }} as target
    using (
        {{ affected_key_query }}
    ) as affected
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
        none,
        affected_key_query
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
