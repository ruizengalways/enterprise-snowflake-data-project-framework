# Current context

This file describes the current architecture, not a chronological PR log. For a new conversation, read `docs/NEXT_CHAT_HANDOFF.md` first, then this file and the architecture document most relevant to the task.

## Current Framework release identity

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.27.0
```

Always re-check current `main`, open PRs and CI before changing code. Green static CI is not Snowflake certification. A revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

## Framework boundary

This repository is a developer toolkit/bootstrapper for readable Snowflake domain repositories. It generates explicit source code, validates reviewed contracts and provides operational/deployment guardrails. It is **not** a universal runtime interpreter.

Generated implementation and operation units are created once, committed, reviewed and then domain-owned. Framework upgrades never rewrite existing domain implementation SQL in place.

The Framework deliberately does not own source profiling/discovery, one universal ingestion engine, runtime metadata-to-SQL routing, a central SCD engine, business-DQ inference, autonomous production repair, or Bronze-to-Silver execution through dbt.

## Canonical architecture boundary

Logical vocabulary:

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

One business domain normally owns one repository and one domain database per environment. A domain may contain many source systems. Source identity remains explicit in paths and object names. Writable `CONTROL` is domain-local; enterprise monitoring consumes stable read-only exports.

RAW contracts are reviewed engineering declarations. The Framework never infers business keys, ordering/timestamps, CDC/delete semantics, capture fidelity, idempotency identity or SCD pattern.

```text
pattern
  append | full_refresh | scd1 | scd2 | custom

execution_model
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

## Evidence-driven correctness releases — 0.26 and 0.27

Transport-domain adoption exposed two concrete template defects after the planned architecture roadmap was complete.

### 0.26 — input idempotency

Framework 0.26 prevents duplicate identities inside one append/SCD2 apply or replay batch from bypassing a target-side `NOT EXISTS` check.

```text
same identity + conflicting payload -> FAIL CLOSED with E_IDEMPOTENCY_CONFLICT
same identity + identical payload   -> collapse to one row/event
already persisted identity           -> existing target/event-ledger guard remains
```

Identity joins are NULL-safe with `IS NOT DISTINCT FROM`. Conflict comparison uses a canonical JSON payload signature. Full replay checks conflicts before destructive candidate clearing.

0.26 advanced:

```text
append_stream_task  -> revision 3
scd2_stream_task    -> revision 3
```

See `docs/architecture/INPUT_IDEMPOTENCY.md`.

### 0.27 — replay-stable SCD2 event identity

The Transport SCD2 RAW contract uses retained full-change rows with `source_operation = D` tombstones. Framework 0.26 replay incorrectly converted such a retained row into synthetic `ESF_STREAM_ACTION = DELETE`, mixing source delete semantics with Snowflake physical Stream action.

Framework 0.27 separates them:

```text
retained Bronze row replay       -> synthetic ESF_STREAM_ACTION = INSERT
source tombstone delete meaning  -> reviewed operation column / delete_values
```

History construction still treats the reviewed tombstone as a delete boundary and does not emit it as an active SCD2 row. Only `scd2_stream_task` advances from revision 3 to **revision 4**. `append_stream_task` remains revision 3.

`esf upgrade-plan` stays read-only. A 0.26 SCD2 rev3 scaffold reports `UPDATE_AVAILABLE`; a 0.26 append rev3 scaffold remains `CURRENT` under 0.27 because its artifact contract did not change.

## Earlier stable contracts

Framework 0.20 established canonical explicit-pipeline metrics: `ROWS_AFFECTED = SQLROWCOUNT` for the primary Silver DML and `DML_QUERY_ID = SQLID` captured immediately after that DML.

Framework 0.21 added guarded release readiness and release audit. `BLOCKED` has no bypass; `REVIEW_REQUIRED` requires explicit operator acceptance and reason.

Framework 0.22 added deterministic template provenance and read-only `esf upgrade-plan` statuses: `CURRENT`, `UPDATE_AVAILABLE`, `ADVISORY`, `UNKNOWN`, `UNVERIFIED`.

Framework 0.23 added narrow version-local Stream/Task operational policy: warehouse, minimum trigger interval, timeout, suspend-after-failures and optional error integration. It does not expose arbitrary schedules or generic task graphs.

Framework 0.24 added explicit audited domain health-evaluator cadence operations through migration `130_health_evaluation_cadence.sql` without editing released migration 040.

Framework 0.25 added migration `140_dynamic_table_observability_enrichment.sql`, enriching the existing Snowflake-native Dynamic Table observability path while keeping `CONTROL.DATASET_OBSERVABILITY_V` as the one unified evidence surface. It does not fabricate Dynamic Table `PIPELINE_RUN` rows.

## Unified observability boundary

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

Unify evidence contracts, not runtime mechanics. Do not add a second competing execution-health abstraction without a concrete missing contract.

## Control Plane migrations

Framework 0.27 adds **no Control migration**. Fresh projects still contain the released chain through 140:

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

Released numbered migrations are immutable. Never edit 001..140 in place after release; append a later migration only when a Control contract actually changes.

Rerunning `esf init-project` materializes missing Framework files but never rewrites an existing domain-owned `control_plane/deploy_manifest.txt`. Engineers review `esf control-plan` and explicitly append adopted migrations without reordering recorded history.

## Apply-once deployment and DDL safety

```text
NEW path                        -> APPLY
recorded + same checksum/order  -> SKIP
checksum/path/order drift       -> BLOCK
unresolved STARTED/FAILED       -> BLOCK
```

New persistent version-owned objects are create-only/fail-closed. Snowflake DDL is not treated as one rollbackable cross-object transaction; partial changes require inspection and explicit remediation.

## DQ / reconciliation / SLA

Dataset-local structural validation writes `CONTROL.DQ_RESULT`; domain-authored reconciliation can write `CONTROL.RECONCILIATION_RESULT`. Candidate evidence remains version-specific and isolated from active production health.

SLA remains logical-dataset policy. Do not infer SLA thresholds from Dynamic Table target lag, version Task configuration, or domain health evaluator cadence.

## dbt / Gold / Semantic

dbt begins at trusted Silver and owns downstream Gold/Mart/Semantic transformation. It never becomes the Bronze-to-Silver execution engine in the current Framework architecture.

## Current evidence-driven priority

After Framework 0.27 is merged and static CI is green, return to `enterprise-snowflake-transport-analytics` and recreate the unmerged shadow Silver implementations from the **exact merged 0.27 SHA**.

Expected current provenance after regeneration:

```text
fleet_mssql.vehicle_status      -> scd2_stream_task revision 4
gtfs_realtime.vehicle_position  -> append_stream_task revision 3
```

Keep them shadow-only: no root Silver deploy-manifest adoption, no Control-plane initialization and no production cutover as a scaffold side effect. Compare legacy dbt Silver against the generated implementations, with explicit tests for duplicate identities, conflicting payloads, tombstone delete/reinsert, same timestamp/sequence, late arrivals and consecutive identical SCD2 state.

Do not add another Framework abstraction merely to continue a roadmap. Prefer live Snowflake certification/integration evidence and concrete domain-adoption defects as the trigger for future changes.
