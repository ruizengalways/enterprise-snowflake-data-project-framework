# Domain control plane

This directory belongs to this domain repository. It is not a shared writable platform runtime.

The SQL under `control_plane/sql/` runs in the domain database context and creates or upgrades a local `CONTROL` schema.

Committed paths in `deploy_manifest.txt` are ordered **migrations**, not a list to replay in full on every deployment. A fresh 0.19 project contains:

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
090_dataset_execution_model.sql
100_dynamic_table_observability.sql
```

The reusable deployment workflow uses `esf-migrate deploy` to create/use `CONTROL.DEPLOYMENT_HISTORY`, checksum the exact committed file bytes and apply only unseen CONTROL/SILVER paths. An already applied/baselined path with the same checksum is skipped. Changed checksum, removed/reordered history, duplicate manifest paths, or unresolved STARTED/FAILED attempts block deployment.

`CONTROL.DEPLOYMENT_HISTORY` itself is created by the migration runner's tiny idempotent bootstrap because the ledger must exist before the first normal migration can be tracked.

For an **existing populated domain adopting apply-once deployment**, do not let the first migration-runner deployment replay the historical manifests. The runner detects existing CONTROL/SILVER objects with empty history and blocks. Review the exact environment against the exact project Git SHA, then explicitly run `esf-migrate baseline ... --confirm-existing-state-reviewed`. Baseline records the existing committed paths and checksums without executing those files.

After a migration has been recorded as SUCCEEDED/BASELINED/REMEDIATED in an environment, treat its path and bytes as immutable. Add a later migration for corrections. Do not edit the applied file in place.

The control plane provides logical dataset registry/lifecycle state, implementation-version identity, execution-model metadata, SLA policy/cadence evaluation, ingestion/Silver/dbt evidence, normalized DQ/reconciliation evidence, health/incidents, version validation, repair audit, deployment history, dashboard views, and stable read-only enterprise health exports.

`060_run_evidence_api.sql` standardizes how source-specific ingestion records BEGIN/SUCCESS/FAILED evidence and extends `DBT_RUN` with invocation/resource identity. It does **not** orchestrate ingestion or own connector checkpoints.

`070_enterprise_health_export.sql` establishes `CONTROL.ENTERPRISE_HEALTH_EXPORT_V` and `CONTROL.DOMAIN_HEALTH_SUMMARY_V`.

`080_data_quality_reconciliation.sql` adds `DQ_RESULT`, `RECONCILIATION_RESULT`, fail-closed record APIs, latest-status views, active-version quality semantics and an optional serverless quality-incident evaluator. Dataset checks remain committed dataset-local SQL; CONTROL never stores executable rule expressions.

`090_dataset_execution_model.sql` separates logical semantics from implementation technology. `CONTROL.DATASET.PATTERN` remains the logical dataset semantic pattern. `CONTROL.DATASET_VERSION.EXECUTION_MODEL` and `PRIMARY_RUNTIME_OBJECT` identify how one implementation version executes. Existing pre-0.19 versions are backfilled from their already-recorded Task/apply objects; the migration does not infer a new technology.

`100_dynamic_table_observability.sql` normalizes Snowflake-native Dynamic Table refresh evidence from `INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY`. It does not fabricate `CONTROL.PIPELINE_RUN` rows. The operational view chooses Stream/Task or Dynamic Table evidence according to the active implementation version.

The health and quality tasks are created suspended. Resume them explicitly only after migration review.

## Upgrade and deployment gate

Rerunning `esf init-project` may create newly introduced missing control migration files, but it never edits this domain-owned `deploy_manifest.txt`.

Use:

```bash
esf control-plan --project-root .
```

for the human-readable upgrade report. Review and explicitly append required migrations. For 0.19 adoption, append 090 and 100 after all previously applied manifest entries; do not reorder history merely to make numeric filenames look sorted around domain-owned migrations.

The reusable deployment workflow additionally runs:

```bash
esf-control-preflight --project-root .
```

before Snowflake authentication. Deployment is blocked when a Framework-known migration is missing from the repo/manifest, duplicated, or out of Framework relative order. Domain-owned extra control migrations remain allowed; the normal manifest path/file checks still apply to them.

After authentication, `esf-migrate deploy` enforces the environment-specific apply-once/checksum history. The preflight and migration runner are complementary: preflight checks the committed baseline before touching Snowflake; migration history decides whether each exact file is NEW, already applied, or blocked in that environment.

The normal GitHub deployment path serializes one deployment per domain/environment with `cancel-in-progress: false` so two deployments do not race the same unseen migration.

## Execution-model boundary

`PATTERN` and `EXECUTION_MODEL` are intentionally different concepts:

```text
PATTERN          = append / full_refresh / scd1 / scd2 / custom
EXECUTION_MODEL  = stream_task / dynamic_table / batch_sql / custom
```

A logical SCD1 dataset can therefore have v1 implemented with Stream+Task and v2 implemented with a Dynamic Table while retaining the same published semantic contract. `TARGET_LAG`, Dynamic Table warehouse and refresh mode are version execution configuration; they are not replacements for logical `CONTROL.SLA_POLICY`.

See `docs/architecture/EXECUTION_MODELS.md`, `docs/architecture/DEPLOYMENT_CONTROL_PREFLIGHT.md` and `docs/architecture/APPLY_ONCE_MIGRATIONS.md` in the Framework repository.

Enterprise monitoring may UNION the stable export views across domains, but must not write back into domain control schemas. Cross-domain roles/grants belong in platform infrastructure.

The control plane records operational state and evidence. It does not dynamically route SCD patterns, generate transformation SQL at runtime, infer business DQ rules, decide reconciliation logic, or turn dbt into a Bronze-to-Silver engine.

Repair SQL is intentionally reviewed and executed by engineers. The control plane records repair activity; it is not an autonomous repair engine.
