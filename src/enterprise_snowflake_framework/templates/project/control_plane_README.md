# Domain control plane

This directory belongs to this domain repository. It is not a shared writable platform runtime.

The SQL under `control_plane/sql/` runs in the domain database context and creates or upgrades the domain-local `CONTROL` schema. Committed paths in `deploy_manifest.txt` are ordered **apply-once migrations**, not a replay list.

A fresh Framework 0.25 project contains:

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
140_dynamic_table_observability_enrichment.sql
```

After a migration is recorded as SUCCEEDED/BASELINED/REMEDIATED, its path and bytes are immutable in that environment. Corrections use a later migration. Changed checksums, removed/reordered history, duplicate manifest paths, or unresolved STARTED/FAILED attempts block deployment.

For an existing domain, rerunning `esf init-project` may materialize newly introduced Framework files, but never rewrites the domain-owned `deploy_manifest.txt`. Use `esf control-plan --project-root .`, review the gap, and append adopted migrations without reordering historical entries.

## Main Control contracts

The Control Plane owns normalized operational evidence and state, not transformation runtime routing:

```text
logical dataset/version registry
SLA policy and health/incident state
ingestion / Silver / dbt run evidence
DQ / reconciliation evidence
release / repair / lifecycle audit
deployment history
read-only enterprise health exports
```

Important later migrations:

```text
090_dataset_execution_model.sql
  -> version execution model and primary runtime identity

100_dynamic_table_observability.sql
  -> original native Dynamic Table observability boundary

110_pipeline_execution_metrics.sql
  -> canonical explicit-run rows/query-id metrics

120_release_readiness.sql
  -> release readiness and RELEASE_RUN audit

130_health_evaluation_cadence.sql
  -> audited health evaluator cadence changes without silently retuning 040

140_dynamic_table_observability_enrichment.sql
  -> richer native Dynamic Table refresh/scheduling diagnostics on the existing views
```

## Dynamic Table observability

Dynamic Tables are observed through Snowflake-native metadata rather than fake `CONTROL.PIPELINE_RUN` rows:

```text
INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
INFORMATION_SCHEMA.DYNAMIC_TABLES
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V
  -> CONTROL.DATASET_OBSERVABILITY_V
```

Migration 140 enriches the existing detail view with refresh action/trigger/reinitialization reason, native statistics, changed inputs, scheduling state/reason, target/mean/maximum lag, time above target lag, within-target ratio, last completed state and an executing refresh query id.

Raw native diagnostic payloads remain in `DYNAMIC_TABLE_REFRESH_STATUS_V`; the common dataset view exposes only compact triage fields. A currently executing refresh is normalized to `RUNNING` ahead of a previous completed state.

Migration 100 is released and remains unchanged. Migration 140 does not create a second unified health view, a new runtime ledger, or Account Usage dependency for low-latency health.

## Health evaluator cadence

Released `040_health_task.sql` historically created `CONTROL.EVALUATE_DOMAIN_HEALTH_TASK` with a one-minute schedule. 040 remains immutable.

Migration 130 adds audit/read surfaces but performs no `ALTER TASK`. Generate a reviewed cadence operation instead:

```bash
esf health-cadence-sql health-every-5m \
  --interval-seconds 300 \
  --reason "Five-minute health evaluation is sufficient for this domain" \
  --resume-after \
  --project-root .
```

Use `--leave-suspended` when that is the intended final state. Partial operation failure leaves STARTED audit evidence and is not blindly retried.

## Upgrade and deployment gate

Before Snowflake authentication, the reusable workflow runs:

```bash
esf-control-preflight --project-root .
```

After authentication, `esf-migrate deploy` enforces environment-specific apply-once/checksum history. Existing populated environments with empty history require an explicit reviewed baseline; historical migrations are not blindly replayed.

## Execution-model boundary

```text
PATTERN          = append / full_refresh / scd1 / scd2 / custom
EXECUTION_MODEL  = stream_task / dynamic_table / batch_sql / custom
```

Version Task settings and Dynamic Table target lag/warehouse/refresh mode are execution policy, not logical SLA. Dynamic Table refresh statistics also are not reinterpreted as explicit-procedure `ROWS_AFFECTED` metrics.

Enterprise monitoring may aggregate stable read-only domain exports but must not write back into domain Control schemas.

The Control Plane does not dynamically route SCD patterns, generate transformation SQL at runtime, infer business DQ/reconciliation rules, own connector checkpoints, or turn dbt into a Bronze-to-Silver engine. Repair, release, lifecycle and health-cadence changes remain explicit engineer-reviewed operations.
