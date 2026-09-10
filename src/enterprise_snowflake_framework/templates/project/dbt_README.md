# dbt in this domain

This dbt project starts from trusted Silver and owns exploratory Gold/Mart/Semantic logic for this domain.

## Run evidence

New projects call `esf_record_dbt_results(results)` from `on-run-end`. The macro writes one `CONTROL.DBT_RUN` row per model result.

A dbt model participates in one logical dataset's Gold health only when that relationship is explicit:

```yaml
models:
  - name: customer_gold
    config:
      meta:
        esf_dataset_id: fleet_mssql.customer
```

Do not assign `esf_dataset_id` to a business mart that combines several logical datasets just to make the dashboard green. Such a mart is still valid dbt work; it simply is not the one-to-one Gold publication used for that dataset's stage SLA.

The macro records dbt status, execution time, invocation id, model unique id and the latest successful Silver data timestamp available when the model finished. It does not infer a Gold business-event timestamp. If a domain needs a stronger Gold freshness contract, add domain-owned evidence explicitly.

## Existing repositories

`esf init-project` never rewrites an existing `dbt/dbt_project.yml`. After upgrading the Framework, the macro/readme may appear as new files while the old project file remains unchanged. To enable run logging, review the new macro and add this hook manually:

```yaml
on-run-end:
  - "{{ esf_record_dbt_results(results) }}"
```

Deploy control migration `control_plane/sql/060_run_evidence_api.sql` before enabling the hook.
