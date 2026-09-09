{% macro esf_task_history_sql(task_name, result_limit=100, error_only=false) -%}
    {%- if task_name is not string or task_name | trim == '' -%}
        {{ exceptions.raise_compiler_error('task_name must be a non-empty task name') }}
    {%- endif -%}
    {%- if result_limit | int < 1 or result_limit | int > 10000 -%}
        {{ exceptions.raise_compiler_error('result_limit must be between 1 and 10000') }}
    {%- endif -%}
select *
from table(
    information_schema.task_history(
        result_limit => {{ result_limit | int }},
        task_name => '{{ task_name | replace("'", "''") }}',
        error_only => {{ 'true' if error_only else 'false' }}
    )
)
order by scheduled_time desc
{%- endmacro %}

{% macro esf_complete_task_graphs_sql(root_task_name, result_limit=100, error_only=false) -%}
    {%- if root_task_name is not string or root_task_name | trim == '' -%}
        {{ exceptions.raise_compiler_error('root_task_name must be a non-empty unqualified root task name') }}
    {%- endif -%}
    {%- if '.' in root_task_name -%}
        {{ exceptions.raise_compiler_error('Snowflake COMPLETE_TASK_GRAPHS accepts an unqualified ROOT_TASK_NAME') }}
    {%- endif -%}
    {%- if result_limit | int < 1 or result_limit | int > 10000 -%}
        {{ exceptions.raise_compiler_error('result_limit must be between 1 and 10000') }}
    {%- endif -%}
select *
from table(
    information_schema.complete_task_graphs(
        result_limit => {{ result_limit | int }},
        root_task_name => '{{ root_task_name | replace("'", "''") }}',
        error_only => {{ 'true' if error_only else 'false' }}
    )
)
order by completed_time desc
{%- endmacro %}
