# Domain control plane

This directory belongs to this domain repository. It is not a shared writable platform runtime.

The SQL under `control_plane/sql/` is designed to run in the domain database context and create a local `CONTROL` schema.

Apply the files in order:

```text
001_objects.sql
010_observability_views.sql
020_refresh_health.sql
```

The first implementation provides the operational foundation for:

- logical dataset registry
- dataset versions
- SLA policies
- ingestion / Silver / dbt run ledgers
- current dataset health
- incidents
- version validation
- repair audit
- dashboard-ready views

The control plane records operational state and evidence. It does not dynamically route SCD patterns or generate transformation SQL at runtime.

Cross-domain monitoring should read each domain's stable `CONTROL.DATASET_HEALTH_V` and aggregate those views elsewhere. Do not add writes from another domain into this control schema.

Repair SQL is intentionally reviewed and executed by engineers. The control plane records repair activity; it is not an autonomous repair engine.
