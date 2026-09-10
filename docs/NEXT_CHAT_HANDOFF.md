# Next chat handoff

Read this file first when continuing the Framework. Then read `docs/CURRENT_CONTEXT.md` and the architecture document most relevant to the next task.

## Current Framework release identity

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.25.0
```

Always re-check current `main`, open PRs and CI before changing code. Static CI is not Snowflake certification. A revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

## Completed roadmap work

Do not redesign these contracts unless new evidence identifies a defect.

### 0.20 — canonical explicit-pipeline metrics

`110_pipeline_execution_metrics.sql` established `ROWS_AFFECTED` as the primary Silver DML `SQLROWCOUNT` and `DML_QUERY_ID` as the immediately captured `SQLID`. Pattern-specific work belongs in `METRICS`; historical insert/update/delete fields are compatibility evidence. See `docs/architecture/RUN_EVIDENCE.md`.

### 0.21 — release readiness

`120_release_readiness.sql` plus generated release bundles enforce active/candidate invariants, runtime/DQ/comparison freshness, hard preflight/postflight, `CONTROL.RELEASE_RUN` audit, grant-preserving cutover and guarded rollback. `BLOCKED` has no bypass; `REVIEW_REQUIRED` requires explicit acceptance and reason.

### 0.22 — template provenance

New implementation versions declare deterministic `framework_version`, `template_id`, `template_revision`, and `template_digest`. `esf upgrade-plan` is read-only. Pre-provenance versions are `UNKNOWN`; digest mismatch is `UNVERIFIED`; never infer old template revision from SQL. See `docs/architecture/TEMPLATE_PROVENANCE.md`.

### 0.23 — version-local Task operational policy

`stream_task` versions can explicitly declare Task warehouse, minimum trigger interval, timeout, suspend-after-failures and error integration. These are version execution policy, not source semantics or SLA. Do not expose arbitrary schedules, generic task graphs or a universal readiness DSL. See `docs/architecture/TASK_OPERATIONAL_CONFIG.md`.

### 0.24 — configurable domain health evaluation cadence

Released `040_health_task.sql` remains unchanged. `130_health_evaluation_cadence.sql` adds audit/read surfaces, while `esf health-cadence-sql` generates an explicit reviewed Task schedule operation. Migration 130 itself performs no `ALTER TASK`; partial operation failure leaves `STARTED` evidence and is not blindly retried. See `docs/architecture/HEALTH_EVALUATION_CADENCE.md`.

### 0.25 — Dynamic Table observability enrichment

Released `100_dynamic_table_observability.sql` remains unchanged. New migration:

```text
140_dynamic_table_observability_enrichment.sql
```

replaces only the existing observability views with richer Snowflake-native evidence.

`CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V` now normalizes recent/current metadata from:

```text
INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
INFORMATION_SCHEMA.DYNAMIC_TABLES
```

including refresh action/trigger/reinitialization reason, native statistics, changed inputs, scheduling state/reason, target/mean/maximum lag, time above target lag, time-within-target ratio, last completed refresh state and executing query id.

`CONTROL.DATASET_OBSERVABILITY_V` remains the one cross-execution-model surface and exposes only a compact Dynamic Table triage subset. Raw native payloads stay in the detail view. A currently executing refresh wins over the previous completed state and normalizes to `RUNNING`.

The Framework does **not** create Dynamic Table `PIPELINE_RUN` rows, does not introduce another unified health view, and does not move low-latency domain health to Account Usage merely for longer retention. See `docs/architecture/DYNAMIC_TABLE_OBSERVABILITY.md`.

0.25 changes project-level Control migration content only. Dataset scaffold artifact contracts are unchanged, so existing template revisions remain current.

## Canonical architecture vocabulary

Logical layers:

```text
Bronze
Silver
Gold / Marts
Semantic
Control
```

Default physical schemas:

```text
BRONZE
SILVER
GOLD_MARTS
SEMANTIC
CONTROL
```

A domain owns writable `CONTROL`. Cross-domain observability is read-only aggregation.

## Current Control Plane migration chain

Fresh 0.25 projects contain:

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

Released numbered migrations are immutable. Never edit 001..140 in place after release; append a later migration.

For an older domain, rerun `esf init-project` to materialize missing Framework files, then use `esf control-plan`. Existing `control_plane/deploy_manifest.txt` stays domain-owned and is never silently rewritten; explicitly append adopted migrations without reordering recorded history.

## Stable execution-model boundary

```text
logical pattern
  append | full_refresh | scd1 | scd2 | custom

execution model
  stream_task | dynamic_table | batch_sql | custom
```

Supported combinations remain deliberately narrow:

```text
append       + stream_task   = supported
full_refresh + stream_task   = supported
full_refresh + dynamic_table = supported
full_refresh + batch_sql     = supported
scd1         + stream_task   = supported
scd1         + dynamic_table = supported
scd2         + stream_task   = supported
custom       + custom        = domain-owned
```

Unsupported combinations fail closed. `procedure` is an implementation artifact, not an execution model.

## Observability boundary

```text
explicit Stream/Task or batch apply
  -> CONTROL.PIPELINE_RUN
  -> CONTROL.PIPELINE_EXECUTION_METRICS_V

Dynamic Table
  -> INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
  -> INFORMATION_SCHEMA.DYNAMIC_TABLES
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V

both
  -> CONTROL.DATASET_OBSERVABILITY_V
  -> health / SLA / incidents
```

Do not fabricate Dynamic Table `PIPELINE_RUN` rows or create a second unified execution-health abstraction.

## Ownership and deployment guardrails

Framework generates once; domain owns forever. CONTROL and SILVER are checksum-locked apply-once migrations. New persistent version-owned objects are create-only/fail-closed. Candidate deployment never changes stable consumer objects; explicit release/rollback is the stable-view replacement boundary.

Do not introduce deployment-time scaffolding, hidden metadata routing, one central SCD runtime, arbitrary orchestration DSLs, or dbt as the Bronze-to-Silver engine.

## Next implementation priority

There is no remaining pre-planned architecture prompt after 0.25. Do not continue by inventing abstractions.

The next change should come from concrete evidence, preferably in this order:

```text
1. live Snowflake certification/integration result for the exact current main SHA
2. a real domain adoption / upgrade issue
3. an operational gap demonstrated by existing Control evidence
4. a Snowflake platform capability change that materially improves the current contracts
```

When a live test identifies a problem, fix the narrow contract that owns it. Preserve released migration immutability and existing runtime boundaries.

## New conversation starter

```text
Continue enterprise-snowflake framework.
Read docs/NEXT_CHAT_HANDOFF.md and docs/CURRENT_CONTEXT.md.
Re-check current GitHub main, open PRs and CI before changing code.
The planned architecture roadmap through 0.25 is complete; continue only from concrete evidence.
Prefer live Snowflake certification/integration or a real domain adoption defect over speculative abstraction.
```
