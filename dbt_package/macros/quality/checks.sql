{% macro esf_freshness_check_sql(
    relation,
    timestamp_column,
    warn_after_minutes,
    error_after_minutes,
    check_name='source_freshness'
) -%}
    {%- if warn_after_minutes | int < 1 or error_after_minutes | int < 1 -%}
        {{ exceptions.raise_compiler_error('freshness thresholds must be positive minutes') }}
    {%- endif -%}
    {%- if warn_after_minutes | int >= error_after_minutes | int -%}
        {{ exceptions.raise_compiler_error('warn_after_minutes must be less than error_after_minutes') }}
    {%- endif -%}
with observed as (
    select max({{ adapter.quote(timestamp_column) }}) as observed_timestamp
    from {{ relation }}
), evaluated as (
    select
        observed_timestamp,
        case
            when observed_timestamp is null then null
            else greatest(0, datediff('minute', observed_timestamp, current_timestamp()))
        end as age_minutes
    from observed
)
select
    'freshness' as check_type,
    '{{ check_name | replace("'", "''") }}' as check_name,
    case
        when observed_timestamp is null then 'FAIL'
        when age_minutes > {{ error_after_minutes | int }} then 'FAIL'
        when age_minutes > {{ warn_after_minutes | int }} then 'WARN'
        else 'PASS'
    end as status,
    'age_minutes' as measure_name,
    to_variant(age_minutes) as observed_value,
    object_construct(
        'warn_after_minutes', {{ warn_after_minutes | int }},
        'error_after_minutes', {{ error_after_minutes | int }}
    ) as expected_value,
    object_construct_keep_null(
        'observed_timestamp', observed_timestamp,
        'evaluated_at', current_timestamp()
    ) as details
from evaluated
{%- endmacro %}

{% macro esf_reconciliation_metrics_sql(
    relation,
    business_key_columns=[],
    source_timestamp_column=none
) -%}
    {%- if business_key_columns is string -%}
        {{ exceptions.raise_compiler_error('business_key_columns must be a list') }}
    {%- endif -%}
select
    count(*) as row_count
    {%- if business_key_columns | length > 0 %},
    count(distinct
        {%- for column in business_key_columns %}
        {{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}
        {%- endfor %}
    ) as distinct_business_key
    {%- endif %}
    {%- if source_timestamp_column is not none %},
    min({{ adapter.quote(source_timestamp_column) }}) as min_source_timestamp,
    max({{ adapter.quote(source_timestamp_column) }}) as max_source_timestamp
    {%- endif %}
from {{ relation }}
{%- endmacro %}

{% macro esf_reconciliation_compare_sql(
    left_relation,
    right_relation,
    left_label='source',
    right_label='target',
    business_key_columns=[],
    source_timestamp_column=none,
    check_name='row_reconciliation'
) -%}
with left_metrics as (
    {{ enterprise_snowflake_framework.esf_reconciliation_metrics_sql(
        left_relation,
        business_key_columns,
        source_timestamp_column
    ) }}
), right_metrics as (
    {{ enterprise_snowflake_framework.esf_reconciliation_metrics_sql(
        right_relation,
        business_key_columns,
        source_timestamp_column
    ) }}
)
select
    'reconciliation' as check_type,
    '{{ check_name | replace("'", "''") }}' as check_name,
    case
        when left_metrics.row_count = right_metrics.row_count
        {%- if business_key_columns | length > 0 %}
         and left_metrics.distinct_business_key = right_metrics.distinct_business_key
        {%- endif %}
        {%- if source_timestamp_column is not none %}
         and equal_null(left_metrics.min_source_timestamp, right_metrics.min_source_timestamp)
         and equal_null(left_metrics.max_source_timestamp, right_metrics.max_source_timestamp)
        {%- endif %}
        then 'PASS'
        else 'FAIL'
    end as status,
    'metric_bundle' as measure_name,
    object_construct_keep_null(
        'label', '{{ left_label | replace("'", "''") }}',
        'row_count', left_metrics.row_count
        {%- if business_key_columns | length > 0 %},
        'distinct_business_key', left_metrics.distinct_business_key
        {%- endif %}
        {%- if source_timestamp_column is not none %},
        'min_source_timestamp', left_metrics.min_source_timestamp,
        'max_source_timestamp', left_metrics.max_source_timestamp
        {%- endif %}
    ) as observed_value,
    object_construct_keep_null(
        'label', '{{ right_label | replace("'", "''") }}',
        'row_count', right_metrics.row_count
        {%- if business_key_columns | length > 0 %},
        'distinct_business_key', right_metrics.distinct_business_key
        {%- endif %}
        {%- if source_timestamp_column is not none %},
        'min_source_timestamp', right_metrics.min_source_timestamp,
        'max_source_timestamp', right_metrics.max_source_timestamp
        {%- endif %}
    ) as expected_value,
    null::variant as details
from left_metrics
cross join right_metrics
{%- endmacro %}

{% macro esf_record_check_result_sql(
    check_relation,
    check_query,
    run_id,
    attempt_number,
    project_code,
    environment,
    dataset_id
) -%}
insert into {{ check_relation }} (
    run_id,
    attempt_number,
    project_code,
    environment,
    dataset_id,
    check_type,
    check_name,
    status,
    measure_name,
    observed_value,
    expected_value,
    details
)
select
    {{ enterprise_snowflake_framework.esf_sql_literal(run_id) }},
    {{ attempt_number | int }},
    {{ enterprise_snowflake_framework.esf_sql_literal(project_code) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(environment) }},
    {{ enterprise_snowflake_framework.esf_sql_literal(dataset_id) }},
    check_type,
    check_name,
    status,
    measure_name,
    observed_value,
    expected_value,
    details
from (
    {{ check_query }}
) as check_result
{%- endmacro %}
