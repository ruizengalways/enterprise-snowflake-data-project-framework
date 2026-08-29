{% macro esf_scd2_target_table_sql(
    target_relation,
    source_relation,
    transient=false,
    comment=none
) -%}
    {%- if target_relation is not string or target_relation | trim == '' -%}
        {{ exceptions.raise_compiler_error('target_relation must be a non-empty Snowflake relation') }}
    {%- endif -%}
    {%- if source_relation is not string or source_relation | trim == '' -%}
        {{ exceptions.raise_compiler_error('source_relation must be a non-empty Snowflake table relation') }}
    {%- endif -%}
create{% if transient %} transient{% endif %} table if not exists {{ target_relation }} like {{ source_relation }};

alter table {{ target_relation }} add column if not exists _esf_valid_from timestamp_tz;
alter table {{ target_relation }} add column if not exists _esf_valid_to timestamp_tz;
alter table {{ target_relation }} add column if not exists _esf_is_current boolean;
alter table {{ target_relation }} add column if not exists _esf_version_ordinal number(38, 0);
{%- if comment is not none %}
alter table {{ target_relation }} set comment = '{{ comment | replace("'", "''") }}';
{%- endif %}
{%- endmacro %}
