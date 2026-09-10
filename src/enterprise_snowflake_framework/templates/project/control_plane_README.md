# Domain control plane

This directory belongs to this domain repository. It is not a shared writable platform runtime.

The SQL under `control_plane/sql/` is designed to run in the domain database context and create a local `CONTROL` schema.

Committed paths in `deploy_manifest.txt` are ordered **migrations**, not a list to replay in full on every deployment. The current starter contains:

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

The reusable deployment workflow uses `esf-migrate deploy` to create/use `CONTROL.DEPLOYMENT_HISTORY`, checksum the exact committed file bytes and apply only unseen CONTROL/SILVER paths. An already applied/baselined path with the same checksum is skipped. Changed checksum, removed/reordered history, duplicate manifest paths, or unresolved STARTED/FAILED attempts block deployment.

`CONTROL.DEPLOYMENT_HISTORY` itself is created by the migration runner's tiny idempotent bootstrap because the ledger must exist before the first normal migration can be tracked.

For an **existing populated domain adopting apply-once deployment**, do not let the first migration-runner deployment replay the historical manifests. The runner detects existing CONTROL/SILVER objects with empty history and blocks. Review the exact environment against the exact project Git SHA, then explicitly run `esf-migrate baseline ... --confirm-existing-state-reviewed`. Baseline records the existing committed paths and checksums without executing those files.

After a migration has been recorded as SUCCEEDED/BASELINED/REMEDIATED in an environment, treat its path and bytes as immutable. Add a later migration for corrections. Do not edit the applied file in place.

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
- deployment history
- dashboard-ready views
- a small ingestion run-evidence API
- stable DQ/reconciliation evidence APIs
- a stable read-only enterprise health export contract

`060_run_evidence_api.sql` standardizes how source-specific ingestion records BEGIN/SUCCESS/FAILED evidence and extends `DBT_RUN` with invocation/resource identity. It does **not** orchestrate ingestion or own connector checkpoints.

`070_enterprise_health_export.sql` establishes `CONTROL.ENTERPRISE_HEALTH_EXPORT_V` and `CONTROL.DOMAIN_HEALTH_SUMMARY_V`.

`080_data_quality_reconciliation.sql` adds `DQ_RESULT`, `RECONCILIATION_RESULT`, fail-closed record APIs, latest-status views, active-version quality semantics and an optional serverless quality-incident evaluator. It also extends the stable health/export views with `DQ_STATUS`, `RECONCILIATION_STATUS`, `LAST_DQ_AT` and `LAST_RECONCILIATION_AT`. Dataset checks remain committed dataset-local SQL; CONTROL never stores executable rule expressions.

The quality-incident task is created suspended. Resume it explicitly only after migration review. Existing health tasks are not replaced by migration 080.

## Upgrade and deployment gate

Rerunning `esf init-project` may create a newly introduced missing control migration, but it never edits this domain-owned `deploy_manifest.txt`.

Use:

```bash
esf control-plan --project-root .
```

for the human-readable upgrade report. Review and explicitly append required migrations.

The reusable deployment workflow additionally runs:

```bash
esf-control-preflight --project-root .
```

before Snowflake authentication. Deployment is blocked when a Framework-known migration is missing from the repo/manifest, duplicated, or out of Framework relative order. Domain-owned extra control migrations remain allowed; the normal manifest path/file checks still apply to them.

After authentication, `esf-migrate deploy` enforces the environment-specific apply-once/checksum history. The preflight and migration runner are complementary: preflight checks the committed baseline before touching Snowflake; migration history decides whether each exact file is NEW, already applied, or blocked in that environment.

The normal GitHub deployment path serializes one deployment per domain/environment with `cancel-in-progress: false` so two deployments do not race the same unseen migration.

See `docs/architecture/DEPLOYMENT_CONTROL_PREFLIGHT.md` and `docs/architecture/APPLY_ONCE_MIGRATIONS.md` in the Framework repository.

Enterprise monitoring may UNION the stable export views across domains, but must not write back into domain control schemas. Cross-domain roles/grants belong in platform infrastructure.

The control plane records operational state and evidence. It does not dynamically route SCD patterns, generate transformation SQL at runtime, infer business DQ rules, or decide reconciliation logic.

Repair SQL is intentionally reviewed and executed by engineers. The control plane records repair activity; it is not an autonomous repair engine.
