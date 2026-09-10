{% macro esf_sql_literal(value) -%}
    {%- if value is none -%}
        NULL
    {%- else -%}
        '{{ (value | string) | replace("'", "''") }}'
    {%- endif -%}
{%- endmacro %}

{% macro esf_record_dbt_results(results) %}
    {#
      Records model-level dbt execution evidence into the domain-local CONTROL.DBT_RUN table.

      Only models with config.meta.esf_dataset_id participate in per-dataset Gold health.
      Unmapped business marts are still valid dbt models; they are simply not treated as the
      Gold publication of one logical source dataset.
    #}
    {% if not execute %}
        select 1
    {% else %}
        {% set model_results = results | selectattr('node.resource_type', 'equalto', 'model') | list %}
        {% if model_results | length == 0 %}
            select 1
        {% else %}
            INSERT INTO CONTROL.DBT_RUN (
                RUN_ID,
                DATASET_ID,
                MODEL_NAME,
                STATUS,
                STARTED_AT,
                COMPLETED_AT,
                SILVER_DATA_MAX_AT,
                GOLD_DATA_MAX_AT,
                GOLD_PUBLISHED_AT,
                ROWS_AFFECTED,
                GIT_COMMIT,
                ERROR_CODE,
                ERROR_MESSAGE,
                INVOCATION_ID,
                RESOURCE_UNIQUE_ID
            )
            {% for res in model_results %}
                {% set meta = res.node.config.meta or {} %}
                {% set dataset_id = meta.get('esf_dataset_id') %}
                {% set raw_status = (res.status | string) | lower %}
                {% if raw_status == 'success' %}
                    {% set esf_status = 'SUCCESS' %}
                {% elif raw_status in ['error', 'fail', 'failed'] %}
                    {% set esf_status = 'FAILED' %}
                {% elif raw_status == 'skipped' %}
                    {% set esf_status = 'SKIPPED' %}
                {% else %}
                    {% set esf_status = raw_status | upper %}
                {% endif %}
                {% set rows_affected = res.adapter_response.get('rows_affected') if res.adapter_response else none %}
                SELECT
                    UUID_STRING(),
                    {{ esf_sql_literal(dataset_id) }},
                    {{ esf_sql_literal(res.node.name) }},
                    '{{ esf_status }}',
                    DATEADD('MILLISECOND', -{{ (res.execution_time * 1000) | int }}, CURRENT_TIMESTAMP()),
                    CURRENT_TIMESTAMP(),
                    {% if dataset_id %}
                    (
                        SELECT SILVER_DATA_MAX_AT
                        FROM CONTROL.PIPELINE_RUN
                        WHERE DATASET_ID = {{ esf_sql_literal(dataset_id) }}
                          AND STATUS = 'SUCCESS'
                        ORDER BY COALESCE(COMPLETED_AT, STARTED_AT, CREATED_AT) DESC
                        LIMIT 1
                    ),
                    {% else %}
                    NULL,
                    {% endif %}
                    NULL,
                    {% if esf_status == 'SUCCESS' %}CURRENT_TIMESTAMP(){% else %}NULL{% endif %},
                    {% if rows_affected is not none and rows_affected != -1 %}{{ rows_affected }}{% else %}NULL{% endif %},
                    {{ esf_sql_literal(env_var('ESF_PROJECT_GIT_SHA', '')) }},
                    {% if esf_status == 'FAILED' %}{{ esf_sql_literal(raw_status) }}{% else %}NULL{% endif %},
                    {% if esf_status == 'FAILED' %}{{ esf_sql_literal(res.message) }}{% else %}NULL{% endif %},
                    {{ esf_sql_literal(invocation_id) }},
                    {{ esf_sql_literal(res.node.unique_id) }}
                {% if not loop.last %}UNION ALL{% endif %}
            {% endfor %}
            ;
        {% endif %}
    {% endif %}
{% endmacro %}
