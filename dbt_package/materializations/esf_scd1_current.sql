{% materialization esf_scd1_current, adapter='snowflake' -%}
    {%- set dataset_id = config.get('esf_dataset_id') -%}
    {%- set dataset = enterprise_snowflake_framework.esf_dataset_metadata(dataset_id) -%}
    {%- set load = dataset.get('load', {}) -%}
    {%- if load.get('strategy') != 'scd1' -%}
        {{ exceptions.raise_compiler_error('esf_scd1_current requires load.strategy=scd1: ' ~ dataset_id) }}
    {%- endif -%}
    {%- set keys = enterprise_snowflake_framework.esf_require_columns(load.get('business_key', []), 'load.business_key') -%}
    {%- set changes = dataset.get('source_contract', {}).get('change_semantics', {}) -%}
    {%- set tombstone = changes.get('delete_semantics') == 'tombstone' -%}
    {%- set operation_column = changes.get('operation_column') -%}
    {%- set delete_values = changes.get('delete_values', []) -%}
    {%- if tombstone and (not operation_column or delete_values | length == 0) -%}
        {{ exceptions.raise_compiler_error('tombstone SCD1 requires source contract operation_column and delete_values: ' ~ dataset_id) }}
    {%- endif -%}
    {%- set target_relation = this -%}
    {%- set temp_relation = make_temp_relation(target_relation) -%}

    {% call statement('stage_source') -%}
create or replace temporary table {{ temp_relation }} as
{{ sql }}
    {%- endcall %}

    {% call statement('ensure_target') -%}
create table if not exists {{ target_relation }} as
select * from {{ temp_relation }} where 1 = 0
    {%- endcall %}

    {% call statement('main') -%}
merge into {{ target_relation }} as target
using {{ temp_relation }} as source
    on {{ enterprise_snowflake_framework.esf_equal_keys('target', 'source', keys) }}
{%- if tombstone %}
when matched and source.{{ adapter.quote(operation_column) }} in (
    {%- for value in delete_values -%}
    '{{ value | replace("'", "''") }}'{% if not loop.last %}, {% endif %}
    {%- endfor -%}
) then delete
{%- endif %}
when matched then update all by name
when not matched
{%- if tombstone %}
    and source.{{ adapter.quote(operation_column) }} not in (
        {%- for value in delete_values -%}
        '{{ value | replace("'", "''") }}'{% if not loop.last %}, {% endif %}
        {%- endfor -%}
    )
{%- endif %}
then insert all by name
    {%- endcall %}

    {% call statement('drop_temp') -%}
drop table if exists {{ temp_relation }}
    {%- endcall %}

    {{ return({'relations': [target_relation]}) }}
{%- endmaterialization %}
