{% macro smoke_bootstrap_handoff_sql() -%}
    {%- set read_sql = enterprise_snowflake_framework.esf_domain_bootstrap_read_sql(
        'HEALTH',
        'smoke_scd2',
        'bootstrap-001'
    ) -%}
    {%- set start_sql = enterprise_snowflake_framework.esf_domain_bootstrap_start_call_sql(
        'HEALTH',
        'smoke_scd2',
        'bootstrap-001',
        "parse_json('{\"position\":100}')",
        'abc123'
    ) -%}
    {%- set landed_sql = enterprise_snowflake_framework.esf_domain_bootstrap_snapshot_landed_call_sql(
        'HEALTH',
        'smoke_scd2',
        'bootstrap-001',
        'snapshot-001',
        'batch-001'
    ) -%}
    {%- set validated_sql = enterprise_snowflake_framework.esf_domain_bootstrap_validated_call_sql(
        'HEALTH',
        'smoke_scd2',
        'bootstrap-001',
        "parse_json('{\"status\":\"PASS\"}')"
    ) -%}
    {%- set commit_sql = enterprise_snowflake_framework.esf_domain_bootstrap_commit_handoff_call_sql(
        'HEALTH',
        'smoke_scd2',
        'bootstrap-001',
        'batch-001',
        'abc123'
    ) -%}
    {%- set rendered =
        '---BOOTSTRAP_READ---\n' ~ read_sql ~
        '\n---BOOTSTRAP_START---\n' ~ start_sql ~
        '\n---BOOTSTRAP_LANDED---\n' ~ landed_sql ~
        '\n---BOOTSTRAP_VALIDATED---\n' ~ validated_sql ~
        '\n---BOOTSTRAP_COMMIT---\n' ~ commit_sql
    -%}
    {%- do log(rendered, info=true) -%}
    {{ return(rendered) }}
{%- endmacro %}
