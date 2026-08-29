{% macro esf_append_only_stream_sql(stream_relation, source_relation, show_initial_rows=false, comment=none) -%}
    {%- if stream_relation is not string or stream_relation | trim == '' -%}
        {{ exceptions.raise_compiler_error('stream_relation must be a non-empty fully-qualified Snowflake identifier') }}
    {%- endif -%}
    {%- if source_relation is not string or source_relation | trim == '' -%}
        {{ exceptions.raise_compiler_error('source_relation must be a non-empty fully-qualified Snowflake identifier') }}
    {%- endif -%}
-- Snowflake owns the CDC offset. Do not recreate an existing stream as part of
-- routine deployment: recreating or replacing an offset-bearing stream can
-- change/reset consumption semantics. Source/APPEND_ONLY changes are explicit
-- migrations, not framework reconciliation.
create stream if not exists {{ stream_relation }}
    on table {{ source_relation }}
    append_only = true
    show_initial_rows = {{ 'true' if show_initial_rows else 'false' }}
{%- if comment is not none %}
    comment = '{{ comment | replace("'", "''") }}'
{%- endif %}
{%- endmacro %}

{% macro esf_triggered_task_sql(
    task_relation,
    stream_relation,
    warehouse,
    body_sql,
    minimum_trigger_interval_seconds=30,
    timeout_ms=3600000,
    auto_retry_attempts=1,
    suspend_after_failures=3,
    overlap_policy='NO_OVERLAP',
    comment=none,
    resume=true
) -%}
    {%- if task_relation is not string or task_relation | trim == '' -%}
        {{ exceptions.raise_compiler_error('task_relation must be a non-empty fully-qualified Snowflake identifier') }}
    {%- endif -%}
    {%- if stream_relation is not string or stream_relation | trim == '' -%}
        {{ exceptions.raise_compiler_error('stream_relation must be a non-empty fully-qualified Snowflake identifier') }}
    {%- endif -%}
    {%- if warehouse is not string or warehouse | trim == '' -%}
        {{ exceptions.raise_compiler_error('warehouse must be a non-empty Snowflake warehouse identifier') }}
    {%- endif -%}
    {%- if body_sql is not string or body_sql | trim == '' -%}
        {{ exceptions.raise_compiler_error('body_sql must be a non-empty SQL statement or Snowflake Scripting block') }}
    {%- endif -%}
    {%- if minimum_trigger_interval_seconds < 10 -%}
        {{ exceptions.raise_compiler_error('minimum_trigger_interval_seconds must be >= 10') }}
    {%- endif -%}
    {%- if timeout_ms <= 0 -%}
        {{ exceptions.raise_compiler_error('timeout_ms must be > 0') }}
    {%- endif -%}
    {%- if auto_retry_attempts < 0 or auto_retry_attempts > 30 -%}
        {{ exceptions.raise_compiler_error('auto_retry_attempts must be between 0 and 30') }}
    {%- endif -%}
    {%- if suspend_after_failures < 0 -%}
        {{ exceptions.raise_compiler_error('suspend_after_failures must be >= 0') }}
    {%- endif -%}
    {%- set overlap = overlap_policy | upper -%}
    {%- if overlap not in ['NO_OVERLAP', 'ALLOW_CHILD_OVERLAP', 'ALLOW_ALL_OVERLAP'] -%}
        {{ exceptions.raise_compiler_error('unsupported task overlap_policy: ' ~ overlap_policy) }}
    {%- endif -%}
    {%- set escaped_stream = stream_relation | replace("'", "''") -%}
create or alter task {{ task_relation }}
    warehouse = {{ adapter.quote(warehouse) }}
    user_task_timeout_ms = {{ timeout_ms }}
    suspend_task_after_num_failures = {{ suspend_after_failures }}
    task_auto_retry_attempts = {{ auto_retry_attempts }}
    user_task_minimum_trigger_interval_in_seconds = {{ minimum_trigger_interval_seconds }}
    overlap_policy = {{ overlap }}
{%- if comment is not none %}
    comment = '{{ comment | replace("'", "''") }}'
{%- endif %}
    when system$stream_has_data('{{ escaped_stream }}')
    as
{{ body_sql }}
;
{%- if resume %}
alter task {{ task_relation }} resume;
{%- endif %}
{%- endmacro %}
