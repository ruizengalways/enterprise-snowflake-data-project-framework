# Current context

This file describes the current architecture, not a chronological PR log. For a new conversation, read `docs/NEXT_CHAT_HANDOFF.md` first, then this file and the architecture document most relevant to the task.

## Current Framework release identity

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.26.0
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

## RAW contract and execution boundary

RAW contracts are reviewed engineering declarations. The Framework never infers business keys, ordering/timestamps, CDC/delete semantics, capture fidelity, idempotency identity or SCD pattern.

```text
pattern
  append | full_refresh | scd1 | scd2 | custom

execution_model
  stream_task | dynamic_table | batch_sql | custom
```

The source manifest owns logical `pattern` and `raw_contract`; implementation technology and version-local execution policy live in `version.yml`.

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

## Input idempotency hardening — 0.26

A real Transport-domain adoption exposed a generated-template defect: target-side `NOT EXISTS` protected against identities already persisted, but two rows carrying the same reviewed `idempotency_key` could still arrive in one apply/replay batch and both pass that check.

Framework 0.26 hardens only `append + stream_task` and `scd2 + stream_task`:

```text
same identity + conflicting payload -> FAIL CLOSED with E_IDEMPOTENCY_CONFLICT
same identity + identical payload   -> deterministic batch collapse to one row
already persisted identity           -> existing target/event-ledger guard remains
```

Append identity is the RAW `idempotency_key`. SCD2 event identity remains RAW `idempotency_key + ESF_STREAM_ACTION`; delete/insert evidence is not redefined.

Apply and replay use the same rule. Full replay checks conflicts before destructive candidate clearing. The Framework does not silently choose a winning conflicting payload and does not become a source checkpoint or universal deduplication engine. See `docs/architecture/INPUT_IDEMPOTENCY.md`.

Template provenance advances only for affected generated contracts:

```text
append_stream_task  revision 2 -> 3
scd2_stream_task    revision 2 -> 3
```

SCD1, full-refresh, Dynamic Table and custom template revisions remain unchanged. `esf upgrade-plan` is read-only and reports older registered revisions as `UPDATE_AVAILABLE`; it never rewrites domain-owned code.

## Earlier stable contracts

Framework 0.20 established canonical explicit-pipeline metrics: `ROWS_AFFECTED = SQLROWCOUNT` for the primary Silver DML and `DML_QUERY_ID = SQLID` captured immediately after that DML.

Framework 0.21 added guarded release readiness and release audit. `BLOCKED` has no bypass; `REVIEW_REQUIRED` requires explicit operator acceptance and reason. `CANDIDATE_VERSION` remains a single-candidate convenience/lock rather than a speculative lifecycle state machine.

Framework 0.22 added deterministic template provenance and read-only `esf upgrade-plan` statuses: `CURRENT`, `UPDATE_AVAILABLE`, `ADVISORY`, `UNKNOWN`, `UNVERIFIED`.

Framework 0.23 added narrow version-local Stream/Task operational policy: warehouse, minimum trigger interval, timeout, suspend-after-failures and optional error integration. It does not expose arbitrary schedules, generic task graphs or universal orchestration metadata.

Framework 0.24 added explicit audited domain health-evaluator cadence operations through migration `130_health_evaluation_cadence.sql` without editing released migration 040 or silently retuning a live Task.

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

Framework 0.26 adds **no Control migration**. Fresh projects still contain the released chain through 140:

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

The planned architecture roadmap through 0.25 is complete. Framework 0.26 exists because real Transport adoption found a concrete template correctness defect.

After 0.26 is merged and static CI is green, return to `enterprise-snowflake-transport-analytics`: regenerate its unmerged shadow Silver v1 implementations from the exact 0.26 SHA, verify revision-3 provenance and idempotency guards, compare against the existing legacy dbt Silver outputs, and only then consider Control/deployment adoption.

Do not add another Framework abstraction merely to continue a roadmap. Prefer live Snowflake certification/integration evidence and concrete domain-adoption defects as the trigger for future changes.
