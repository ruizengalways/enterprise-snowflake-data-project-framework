{% macro esf_native_dmf_schedule_sql(relation, schedule='TRIGGER_ON_CHANGES', object_type='TABLE') -%}
    {%- set kind = object_type | upper -%}
    {%- if kind not in ['TABLE', 'VIEW'] -%}
        {{ exceptions.raise_compiler_error('object_type must be TABLE or VIEW') }}
    {%- endif -%}
    {%- if schedule is not string or schedule | trim == '' -%}
        {{ exceptions.raise_compiler_error('schedule must be a non-empty Snowflake DATA_METRIC_SCHEDULE value') }}
    {%- endif -%}
    {%- if kind == 'VIEW' and schedule | upper == 'TRIGGER_ON_CHANGES' -%}
        {{ exceptions.raise_compiler_error('TRIGGER_ON_CHANGES is not supported for views') }}
    {%- endif -%}
alter {{ kind | lower }} {{ relation }}
    set data_metric_schedule = '{{ schedule | replace("'", "''") }}'
{%- endmacro %}

{% macro esf_native_freshness_dmf_sql(
    relation,
    warn_after_minutes,
    error_after_minutes,
    execute_as_role,
    timestamp_column=none,
    object_type='TABLE',
    warn_expectation='freshness_warn',
    error_expectation='freshness_error'
) -%}
    {%- set kind = object_type | upper -%}
    {%- if kind not in ['TABLE', 'VIEW'] -%}
        {{ exceptions.raise_compiler_error('object_type must be TABLE or VIEW') }}
    {%- endif -%}
    {%- if execute_as_role is not string or execute_as_role | trim == '' -%}
        {{ exceptions.raise_compiler_error('execute_as_role is required for governed DMF associations') }}
    {%- endif -%}
    {%- if warn_after_minutes | int < 1 or error_after_minutes | int < 1 -%}
        {{ exceptions.raise_compiler_error('freshness thresholds must be positive minutes') }}
    {%- endif -%}
    {%- if warn_after_minutes | int >= error_after_minutes | int -%}
        {{ exceptions.raise_compiler_error('warn_after_minutes must be less than error_after_minutes') }}
    {%- endif -%}
    {%- if kind == 'VIEW' and timestamp_column is none -%}
        {{ exceptions.raise_compiler_error('Snowflake FRESHNESS on a view requires a timestamp column') }}
    {%- endif -%}
-- Deployment-time association DDL. EXECUTE AS ROLE lets a governed account
-- role with SELECT + EXECUTE DATA METRIC FUNCTION own execution semantics
-- without taking object OWNERSHIP from the data-project lifecycle.
alter {{ kind | lower }} {{ relation }}
    add data metric function snowflake.core.freshness
    on ({% if timestamp_column is not none %}{{ adapter.quote(timestamp_column) }}{% endif %})
    execute as role {{ adapter.quote(execute_as_role) }}
    expectation {{ warn_expectation }} (value <= {{ (warn_after_minutes | int) * 60 }}),
                {{ error_expectation }} (value <= {{ (error_after_minutes | int) * 60 }})
{%- endmacro %}

{% macro esf_native_unique_count_dmf_sql(
    relation,
    column,
    execute_as_role,
    minimum_unique_count=none,
    object_type='TABLE',
    expectation_name='minimum_unique_count'
) -%}
    {%- set kind = object_type | upper -%}
    {%- if kind not in ['TABLE', 'VIEW'] -%}
        {{ exceptions.raise_compiler_error('object_type must be TABLE or VIEW') }}
    {%- endif -%}
    {%- if execute_as_role is not string or execute_as_role | trim == '' -%}
        {{ exceptions.raise_compiler_error('execute_as_role is required for governed DMF associations') }}
    {%- endif -%}
alter {{ kind | lower }} {{ relation }}
    add data metric function snowflake.core.unique_count
    on ({{ adapter.quote(column) }})
    execute as role {{ adapter.quote(execute_as_role) }}
{%- if minimum_unique_count is not none %}
    expectation {{ expectation_name }} (value >= {{ minimum_unique_count | int }})
{%- endif %}
{%- endmacro %}

{% macro esf_native_dmf_references_sql(relation, object_type='TABLE') -%}
    {%- set kind = object_type | upper -%}
    {%- if kind not in ['TABLE', 'VIEW'] -%}
        {{ exceptions.raise_compiler_error('object_type must be TABLE or VIEW') }}
    {%- endif -%}
select *
from table(
    information_schema.data_metric_function_references(
        ref_entity_name => '{{ relation | replace("'", "''") }}',
        ref_entity_domain => '{{ kind }}'
    )
)
order by metric_database_name, metric_schema_name, metric_name
{%- endmacro %}

{% macro esf_native_dmf_expectations_sql(relation, object_type='TABLE') -%}
    {%- set kind = object_type | upper -%}
    {%- if kind not in ['TABLE', 'VIEW'] -%}
        {{ exceptions.raise_compiler_error('object_type must be TABLE or VIEW') }}
    {%- endif -%}
select *
from table(
    information_schema.data_metric_function_expectations(
        ref_entity_name => '{{ relation | replace("'", "''") }}',
        ref_entity_domain => '{{ kind }}'
    )
)
order by metric_database_name, metric_schema_name, metric_name, expectation_name
{%- endmacro %}

{% macro esf_native_dmf_expectation_status_sql(relation, object_type='TABLE') -%}
    {%- set kind = object_type | upper -%}
    {%- if kind not in ['TABLE', 'VIEW'] -%}
        {{ exceptions.raise_compiler_error('object_type must be TABLE or VIEW') }}
    {%- endif -%}
select *
from table(
    snowflake.local.data_quality_monitoring_expectation_status(
        ref_entity_name => '{{ relation | replace("'", "''") }}',
        ref_entity_domain => '{{ kind }}'
    )
)
order by scheduled_time desc, measurement_time desc
{%- endmacro %}
