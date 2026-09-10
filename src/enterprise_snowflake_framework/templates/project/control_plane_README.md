# Domain control plane

This directory belongs to this domain repository. It is not a shared writable platform runtime.

The SQL under `control_plane/sql/` is designed to run in the domain database context and create a local `CONTROL` schema.

Apply committed files in `deploy_manifest.txt` order. The current starter contains:

```text
001_objects.sql
010_observability_views.sql
020_refresh_health.sql
030_sla_incident_lifecycle.sql
040_health_task.sql
050_dataset_lifecycle_status.sql
060_run_evidence_api.sql
070_enterprise_health_export.sql
080_data_quality_reconciliation.sql
```

The control plane provides:

- logical dataset registry and lifecycle state
- dataset versions
- SLA policies and cadence evaluation
- ingestion / Silver / dbt run ledgers
- normalized DQ and reconciliation evidence
- current dataset health
- automatic ingestion/pipeline/dbt/SLA incidents
- optional automatic DQ/reconciliation incidents
- version validation
- repair audit
- dashboard-ready views
- a small ingestion run-evidence API
- stable DQ/reconciliation evidence APIs
- a stable read-only enterprise health export contract

`060_run_evidence_api.sql` standardizes how source-specific ingestion records BEGIN/SUCCESS/FAILED evidence and extends `DBT_RUN` with invocation/resource identity. It does **not** orchestrate ingestion or own connector checkpoints.

`070_enterprise_health_export.sql` establishes `CONTROL.ENTERPRISE_HEALTH_EXPORT_V` and `CONTROL.DOMAIN_HEALTH_SUMMARY_V`.

`080_data_quality_reconciliation.sql` adds `DQ_RESULT`, `RECONCILIATION_RESULT`, fail-closed record APIs, latest-status views, active-version quality semantics and an optional serverless quality-incident evaluator. It also extends the stable health/export views with `DQ_STATUS`, `RECONCILIATION_STATUS`, `LAST_DQ_AT` and `LAST_RECONCILIATION_AT`. Dataset checks remain committed dataset-local SQL; CONTROL never stores executable rule expressions.

The quality-incident task is created suspended. Resume it explicitly only after migration review. Existing health tasks are not replaced by migration 080.

Enterprise monitoring may UNION the stable export views across domains, but must not write back into domain control schemas. Cross-domain roles/grants belong in platform infrastructure.

The control plane records operational state and evidence. It does not dynamically route SCD patterns, generate transformation SQL at runtime, infer business DQ rules, or decide reconciliation logic.

Repair SQL is intentionally reviewed and executed by engineers. The control plane records repair activity; it is not an autonomous repair engine.
