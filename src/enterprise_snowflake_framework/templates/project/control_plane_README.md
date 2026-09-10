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
```

The control plane provides:

- logical dataset registry and lifecycle state
- dataset versions
- SLA policies and cadence evaluation
- ingestion / Silver / dbt run ledgers
- current dataset health
- automatic ingestion/pipeline/dbt/SLA incidents
- version validation
- repair audit
- dashboard-ready views
- a small ingestion run-evidence API
- a stable read-only enterprise health export contract

`060_run_evidence_api.sql` standardizes how source-specific ingestion records BEGIN/SUCCESS/FAILED evidence and extends `DBT_RUN` with invocation/resource identity. It does **not** orchestrate ingestion or own connector checkpoints.

`070_enterprise_health_export.sql` exposes `CONTROL.ENTERPRISE_HEALTH_EXPORT_V` and `CONTROL.DOMAIN_HEALTH_SUMMARY_V`. Enterprise monitoring may UNION those views across domains, but must not write back into domain control schemas.

The control plane records operational state and evidence. It does not dynamically route SCD patterns or generate transformation SQL at runtime.

Cross-domain monitoring should read each domain's stable enterprise export views and aggregate them elsewhere. Cross-domain grants belong in platform infrastructure. Do not add writes from another domain into this control schema.

Repair SQL is intentionally reviewed and executed by engineers. The control plane records repair activity; it is not an autonomous repair engine.
