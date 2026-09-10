# Next chat handoff

Read this file first when continuing the Framework in a new conversation. Then read `docs/CURRENT_CONTEXT.md` and the architecture document most relevant to the next task.

## Current Framework release identity

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.23.0
```

Always re-check current `main`, open PRs and CI before changing code. Static CI is not Snowflake certification. A revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

## Completed roadmap work

Do not redesign these contracts unless new evidence identifies a defect.

### 0.20 — canonical explicit-pipeline metrics

`110_pipeline_execution_metrics.sql` introduced the stable explicit-run metrics contract. `ROWS_AFFECTED` is the primary DML `SQLROWCOUNT`; `DML_QUERY_ID` is the `SQLID` captured immediately after that DML. Pattern-specific work belongs in `METRICS`. Historical insert/update/delete fields are compatibility evidence, not one universal semantic contract.

See `docs/architecture/RUN_EVIDENCE.md`.

### 0.21 — release readiness and active/candidate invariants

`120_release_readiness.sql` plus the generated release bundle enforce fail-closed release/rollback behavior:

```text
candidate deploy
  -> bootstrap / refresh
  -> catch up
  -> DQ
  -> active-vs-candidate compare
  -> hard preflight
  -> explicit activate
  -> hard postflight
  -> CONTROL.RELEASE_RUN audit
  -> guarded rollback if required
```

`BLOCKED` has no bypass. `REVIEW_REQUIRED` requires explicit acceptance and an operator reason. `CANDIDATE_VERSION` remains a single-candidate convenience/lock; do not replace it with a speculative large lifecycle state machine.

### 0.22 — template provenance and read-only upgrade planning

Every newly scaffolded implementation version declares deterministic provenance:

```text
framework_version
template_id
template_revision
template_digest
```

`esf upgrade-plan --project-root .` is read-only and reports `CURRENT`, `UPDATE_AVAILABLE`, `ADVISORY`, `UNKNOWN` or `UNVERIFIED`. Pre-provenance versions are `UNKNOWN`; never infer a historical template revision from SQL. Digest mismatch is `UNVERIFIED`.

See `docs/architecture/TEMPLATE_PROVENANCE.md`.

### 0.23 — narrow Stream/Task operational policy

Task operational settings are version-local execution policy. They belong in `version.yml`; they do not belong in the source manifest and are not SLA.

A new `stream_task` version declares its warehouse and may opt into:

```text
minimum_trigger_interval_seconds
  -> USER_TASK_MINIMUM_TRIGGER_INTERVAL_IN_SECONDS

timeout_seconds
  -> USER_TASK_TIMEOUT_MS

suspend_after_failures
  -> SUSPEND_TASK_AFTER_NUM_FAILURES

error_integration
  -> ERROR_INTEGRATION

warehouse
  -> WAREHOUSE
```

Optional settings are omitted when unspecified so Snowflake defaults remain in effect. Minimum trigger interval is accepted only for actual Stream-triggered `append`, `scd1` and `scd2` implementations; `full_refresh + stream_task` fails closed for that option because it has no generated Stream readiness condition.

The Framework deliberately does not expose arbitrary schedules, generic `AFTER` graph wiring, `TASK_AUTO_RETRY_ATTEMPTS`, a universal readiness DSL, or a general orchestration framework.

Pre-0.23 Stream/Task versions without a `task:` block remain valid. Because the generated Stream/Task artifact contract changed, Stream/Task template provenance advances from revision 1 to revision 2 while revision 1 remains immutable in the registry.

See `docs/architecture/TASK_OPERATIONAL_CONFIG.md`.

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

Logical and physical names are intentionally separate. `Control` is cross-cutting operational state/evidence, not a medallion transformation layer. Do not build one enterprise-wide writable `PLATFORM_CONTROL` runtime database.

See `docs/architecture/NAMING_AND_LAYERS.md`.

## Current Control Plane migration chain

Fresh projects contain Framework-known migrations through `120_release_readiness.sql`:

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
```

Released numbered migrations are immutable. Never edit 001..120 in place after release; append a later migration.

Rerunning `esf init-project` may materialize new Framework files but never rewrites an existing domain-owned deploy manifest or implementation SQL. Use `esf control-plan` to review adoption gaps and append new migrations without reordering recorded history.

## Stable execution-model boundary

Logical pattern and implementation technology remain separate:

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

Unify evidence contracts, not runtime mechanics:

```text
explicit Stream/Task or batch apply
  -> CONTROL.PIPELINE_RUN
  -> CONTROL.PIPELINE_EXECUTION_METRICS_V

Dynamic Table
  -> INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V

both
  -> CONTROL.DATASET_OBSERVABILITY_V
  -> health / SLA / incidents
```

Do not create fake Dynamic Table `PIPELINE_RUN` rows and do not add a second competing unified execution-health abstraction unless a concrete contract cannot fit the current path.

## Ownership and deployment guardrails

Framework generates once; domain owns forever. Existing dataset/version SQL is never rewritten by a Framework upgrade.

CONTROL and SILVER deployments are checksum-locked apply-once migrations. Same applied path/checksum/order skips; drift, reordering, removed history or unresolved `STARTED`/`FAILED` blocks.

New persistent version-owned objects are create-only/fail-closed. Candidate deployment never modifies stable consumer objects. Stable view replacement is generated only at explicit release/rollback boundaries and preserves grants with `COPY GRANTS`.

Do not introduce deployment-time scaffolding, hidden runtime metadata routing, a central SCD engine, or dbt as the Bronze-to-Silver execution engine.

## Immediate next implementation priority

Continue in this order unless real Snowflake evidence changes the priority:

```text
1. Prompt 11 — configurable domain health evaluation interval

   Current released 040_health_task.sql contains the historical 1 MINUTE schedule.
   NEVER edit released 040.
   Add a new later migration/configuration mechanism.
   Keep the policy domain-level; do not pretend one cadence is globally optimal.

2. Prompt 6 — Dynamic Table observability enrichment

   Migration 100 already provides the native evidence path and health consumes
   CONTROL.DATASET_OBSERVABILITY_V.
   Only add concrete missing Snowflake-native fields if they improve operations.
   Do not build another unified observability layer.
```

Before starting Prompt 11, first finish any open 0.23 PR/CI and verify `main` contains the Task operational policy contract.

## New conversation starter

```text
Continue enterprise-snowflake framework.
Read docs/NEXT_CHAT_HANDOFF.md, docs/CURRENT_CONTEXT.md and the architecture doc for the next task.
Re-check current GitHub main, open PRs and CI before modifying code.
Continue from the immediate-next-work section; do not redesign completed apply-once,
metrics, release-readiness, provenance, Task policy, DDL safety or execution-model work.
```
