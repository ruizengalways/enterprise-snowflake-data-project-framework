# Domain control plane

This directory belongs to this domain repository. It is not a shared writable platform runtime.

The SQL under `control_plane/sql/` runs in the domain database context and creates or upgrades a local `CONTROL` schema.

Committed paths in `deploy_manifest.txt` are ordered **migrations**, not a list to replay in full on every deployment. A fresh Framework 0.24 project contains:

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
110_pipeline_execution_metrics.sql
120_release_readiness.sql
130_health_evaluation_cadence.sql
```

The reusable deployment workflow uses `esf-migrate deploy` to create/use `CONTROL.DEPLOYMENT_HISTORY`, checksum the exact committed file bytes and apply only unseen CONTROL/SILVER paths. An already applied/baselined path with the same checksum is skipped. Changed checksum, removed/reordered history, duplicate manifest paths, or unresolved STARTED/FAILED attempts block deployment.

`CONTROL.DEPLOYMENT_HISTORY` itself is created by the migration runner's tiny idempotent bootstrap because the ledger must exist before the first normal migration can be tracked.

For an **existing populated domain adopting apply-once deployment**, do not let the first migration-runner deployment replay historical manifests. Review the environment against the exact project Git SHA, then explicitly baseline the reviewed existing state. Baseline records committed paths/checksums without executing those files.

After a migration has been recorded as SUCCEEDED/BASELINED/REMEDIATED in an environment, treat its path and bytes as immutable. Add a later migration for corrections. Do not edit the applied file in place.

The Control Plane provides logical dataset registry/lifecycle state, implementation-version identity, execution-model metadata, SLA policy evaluation, ingestion/Silver/dbt evidence, normalized DQ/reconciliation evidence, health/incidents, release/repair audit, deployment history, dashboard views, stable enterprise health exports and an audit contract for domain health-evaluator cadence changes.

Key later migrations:

```text
090_dataset_execution_model.sql
  version execution model / primary runtime identity

100_dynamic_table_observability.sql
  native Dynamic Table refresh evidence without fake PIPELINE_RUN rows

110_pipeline_execution_metrics.sql
  canonical explicit-run rows/query-id metrics

120_release_readiness.sql
  release readiness, active/candidate invariants and RELEASE_RUN audit

130_health_evaluation_cadence.sql
  HEALTH_EVALUATION_CHANGE audit + latest recorded config view
  does NOT alter the historical 040 Task schedule by itself
```

The health and quality tasks are created suspended. Resume them explicitly only after migration review.

## Health evaluator cadence

Released migration `040_health_task.sql` historically created `CONTROL.EVALUATE_DOMAIN_HEALTH_TASK` with a one-minute schedule. 040 remains immutable.

Migration 130 adds the audit/read contract but performs no `ALTER TASK`. To change cadence, generate a reviewed operation:

```bash
esf health-cadence-sql health-every-5m \
  --interval-seconds 300 \
  --reason "Five-minute health evaluation is sufficient for this domain" \
  --resume-after \
  --project-root .
```

Use `--leave-suspended` instead when the intended final Task state is suspended. The Framework never guesses final state. The first contract supports interval schedules from 10 seconds through 8 days and deliberately does not expose cron.

Generated preflight/postflight SQL uses `SHOW TASKS` to verify actual Snowflake state/schedule. `CONTROL.HEALTH_EVALUATION_CONFIG_V` is only the latest successfully recorded Framework operation and is not authoritative for out-of-band Task edits.

Health evaluator cadence is domain operational policy. It is not a logical dataset SLA and is not stored in source manifests or implementation versions.

## Upgrade and deployment gate

Rerunning `esf init-project` may create newly introduced missing Control migration files and runbooks, but it never edits this domain-owned `deploy_manifest.txt`.

Use:

```bash
esf control-plan --project-root .
```

for the human-readable upgrade report. Review and explicitly append required migrations after all previously adopted entries. Do not reorder historical entries merely to make numeric filenames appear sorted around domain-owned migrations.

The reusable deployment workflow additionally runs:

```bash
esf-control-preflight --project-root .
```

before Snowflake authentication. Deployment is blocked when a Framework-known migration is missing from the repo/manifest, duplicated, or out of Framework relative order. Domain-owned extra Control migrations remain allowed; normal path/file checks still apply.

After authentication, `esf-migrate deploy` enforces environment-specific apply-once/checksum history. Preflight checks the committed baseline; migration history decides whether each exact file is NEW, already applied, or blocked in that environment.

## Execution-model boundary

`PATTERN` and `EXECUTION_MODEL` are intentionally different concepts:

```text
PATTERN          = append / full_refresh / scd1 / scd2 / custom
EXECUTION_MODEL  = stream_task / dynamic_table / batch_sql / custom
```

A logical SCD1 dataset can have v1 implemented with Stream+Task and v2 implemented with a Dynamic Table while retaining the same published semantic contract. Version-level Task settings and Dynamic Table target lag/warehouse/refresh mode are implementation execution policy; they are not replacements for logical `CONTROL.SLA_POLICY`.

Enterprise monitoring may aggregate stable domain export views but must not write back into domain Control schemas. Cross-domain roles/grants belong in platform infrastructure.

The Control Plane records operational state and evidence. It does not dynamically route SCD patterns, generate transformation SQL at runtime, infer business DQ/reconciliation rules, decide source ingestion checkpoints, or turn dbt into a Bronze-to-Silver engine.

Repair, release, lifecycle and health-cadence SQL are intentionally reviewed and executed by engineers. The Control Plane records those operations; it is not an autonomous production operator.
