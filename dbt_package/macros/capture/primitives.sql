{% macro esf_require_columns(columns, label) -%}
    {%- if columns is not sequence or columns is string or columns | length == 0 -%}
        {{ exceptions.raise_compiler_error(label ~ " must be a non-empty list of column names") }}
    {%- endif -%}
    {%- for column in columns -%}
        {%- if column is not string or column | trim == '' -%}
            {{ exceptions.raise_compiler_error(label ~ " contains an invalid column name") }}
        {%- endif -%}
    {%- endfor -%}
    {{ return(columns) }}
{%- endmacro %}

{% macro esf_equal_keys(left_alias, right_alias, key_columns) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
    {%- for key in keys -%}
        EQUAL_NULL({{ left_alias }}.{{ adapter.quote(key) }}, {{ right_alias }}.{{ adapter.quote(key) }})
        {%- if not loop.last %} AND {% endif -%}
    {%- endfor -%}
{%- endmacro %}

{% macro esf_latest_observation(relation, key_columns, order_columns) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
    {%- set ordering = enterprise_snowflake_framework.esf_require_columns(order_columns, 'order_columns') -%}
select *
from {{ relation }}
qualify row_number() over (
    partition by
        {%- for key in keys %}
        {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
        {%- endfor %}
    order by
        {%- for column in ordering %}
        {{ adapter.quote(column) }} desc{% if not loop.last %}, {% endif %}
        {%- endfor %}
) = 1
{%- endmacro %}

{% macro esf_snapshot_diff(current_relation, previous_relation, key_columns, hash_column) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
    {%- if hash_column is not string or hash_column | trim == '' -%}
        {{ exceptions.raise_compiler_error('hash_column must be a non-empty column name') }}
    {%- endif -%}
    {%- set sentinel = keys[0] -%}

select
    'INSERT' as _esf_change_type,
    current_snapshot.*
from {{ current_relation }} as current_snapshot
left join {{ previous_relation }} as previous_snapshot
    on {{ enterprise_snowflake_framework.esf_equal_keys('current_snapshot', 'previous_snapshot', keys) }}
where previous_snapshot.{{ adapter.quote(sentinel) }} is null

union all by name

select
    'UPDATE' as _esf_change_type,
    current_snapshot.*
from {{ current_relation }} as current_snapshot
inner join {{ previous_relation }} as previous_snapshot
    on {{ enterprise_snowflake_framework.esf_equal_keys('current_snapshot', 'previous_snapshot', keys) }}
where not EQUAL_NULL(
    current_snapshot.{{ adapter.quote(hash_column) }},
    previous_snapshot.{{ adapter.quote(hash_column) }}
)

union all by name

select
    'DELETE' as _esf_change_type,
    previous_snapshot.*
from {{ previous_relation }} as previous_snapshot
left join {{ current_relation }} as current_snapshot
    on {{ enterprise_snowflake_framework.esf_equal_keys('current_snapshot', 'previous_snapshot', keys) }}
where current_snapshot.{{ adapter.quote(sentinel) }} is null
{%- endmacro %}

{% macro esf_merge_current_state_sql(target_relation, source_relation, key_columns, operation_column=none, delete_values=[]) -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(key_columns, 'key_columns') -%}
    {%- if operation_column is not none and (operation_column is not string or operation_column | trim == '') -%}
        {{ exceptions.raise_compiler_error('operation_column must be a non-empty column name when provided') }}
    {%- endif -%}
    {%- if delete_values is none -%}
        {%- set delete_values = [] -%}
    {%- endif -%}
    {%- if delete_values is string -%}
        {{ exceptions.raise_compiler_error('delete_values must be a list') }}
    {%- endif -%}
merge into {{ target_relation }} as target
using {{ source_relation }} as source
    on {{ enterprise_snowflake_framework.esf_equal_keys('target', 'source', keys) }}
{%- if operation_column is not none and delete_values | length > 0 %}
when matched and source.{{ adapter.quote(operation_column) }} in (
    {%- for value in delete_values -%}
    '{{ value | replace("'", "''") }}'{% if not loop.last %}, {% endif %}
    {%- endfor -%}
) then delete
{%- endif %}
when matched then update all by name
when not matched
{%- if operation_column is not none and delete_values | length > 0 %}
    and source.{{ adapter.quote(operation_column) }} not in (
        {%- for value in delete_values -%}
        '{{ value | replace("'", "''") }}'{% if not loop.last %}, {% endif %}
        {%- endfor -%}
    )
{%- endif %}
then insert all by name
{%- endmacro %}
