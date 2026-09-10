# Current context

This file describes the **current architecture**, not a chronological PR log. For a new conversation, read `docs/NEXT_CHAT_HANDOFF.md` first, then this file and the architecture document most relevant to the task.

## Current Framework release identity

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.25.0
```

Always re-check current `main`, open PRs and CI before modifying code. Green static CI is not Snowflake certification. A revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

## Framework boundary

This repository is a developer toolkit/bootstrapper for readable Snowflake domain repositories. It generates explicit source code, validates contracts and provides operational/deployment guardrails. It is **not** a universal runtime interpreter.

Generated implementation and operation units are created once, committed, reviewed and then domain-owned. Framework upgrades never rewrite existing domain implementation SQL in place.

The Framework deliberately does not own source profiling/discovery, one universal ingestion engine, runtime metadata-to-SQL routing, a central SCD engine, business-DQ inference, autonomous production repair, or Bronze-to-Silver execution through dbt.

## Domain and schema boundary

One business domain normally owns one independent repository and one domain database per environment. A domain may contain many source systems; source boundaries stay explicit in repository paths and Snowflake object names.

Canonical logical vocabulary:

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

`Control` is cross-cutting operational state/evidence, not a medallion transformation layer. Each domain owns writable `CONTROL`; enterprise monitoring consumes read-only exports. See `docs/architecture/NAMING_AND_LAYERS.md`.

## RAW / ingestion / Bronze

RAW contracts are reviewed engineering declarations. The Framework never infers business keys, ordering/timestamps, CDC/delete semantics, capture fidelity or SCD pattern from source metadata.

```text
source evidence / engineering judgement
  -> esf raw-contract-draft
  -> engineer review
  -> esf raw-contract-finalize
  -> esf add-dataset
  -> esf plan / scaffold-preview / scaffold
```

Ingestion remains source-specific. Bronze is retained replay/audit evidence. `CONTROL.INGESTION_RUN` is normalized run evidence, not connector checkpoint ownership.

## Logical pattern vs execution model

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

Unsupported combinations fail closed. `procedure` is an implementation artifact, not an execution model. See `docs/architecture/EXECUTION_MODELS.md`.

## Stream/Task operational policy — 0.23

A `stream_task` implementation can explicitly declare version-local Task settings:

```text
warehouse                        -> WAREHOUSE
minimum_trigger_interval_seconds -> USER_TASK_MINIMUM_TRIGGER_INTERVAL_IN_SECONDS
timeout_seconds                  -> USER_TASK_TIMEOUT_MS
suspend_after_failures           -> SUSPEND_TASK_AFTER_NUM_FAILURES
error_integration                -> ERROR_INTEGRATION
```

Unspecified optional properties are omitted. Minimum trigger interval is allowed only for generated Stream-triggered `append`, `scd1` and `scd2` implementations. The Framework does not expose arbitrary schedules, generic `AFTER` graphs, generic retry orchestration or a universal readiness DSL. See `docs/architecture/TASK_OPERATIONAL_CONFIG.md`.

## Domain health evaluation cadence — 0.24

Released migration `040_health_task.sql` keeps its historical one-minute schedule and is immutable.

Migration `130_health_evaluation_cadence.sql` adds audit/read surfaces but performs **no `ALTER TASK`**. `esf health-cadence-sql` generates an explicit reviewed operation for a 10..691200 second interval and requires the operator to choose `--resume-after` or `--leave-suspended`.

Generated operations record `STARTED` before Task DDL. Partial failure therefore leaves evidence and is never blindly retried. Actual Task schedule/state is verified from Snowflake metadata; the recorded config view is not authoritative for out-of-band edits. See `docs/architecture/HEALTH_EVALUATION_CADENCE.md`.

## Dynamic Table execution and observability — 0.25

Dynamic Table remains first-class only for compatible declarative patterns. Its version-local execution settings remain:

```text
target_lag
warehouse
refresh_mode = incremental | full
```

Dynamic Table implementations intentionally have no fake Stream, Task, apply or replay procedure artifacts. `TARGET_LAG` is execution policy, not logical SLA.

Released migration `100_dynamic_table_observability.sql` established the native evidence path and remains immutable. Migration `140_dynamic_table_observability_enrichment.sql` enriches the same views using current Snowflake Information Schema metadata:

```text
DYNAMIC_TABLE_REFRESH_HISTORY
  -> refresh action / trigger / reinit reason
  -> state / code / message / query id
  -> data timestamp / refresh timing / completion target
  -> native STATISTICS + inputs with changed data

DYNAMIC_TABLES
  -> scheduling state / reason
  -> target / mean / maximum lag
  -> time above target + within-target ratio
  -> latest data timestamp
  -> last completed state
  -> executing refresh query id
```

Detailed native payloads stay in `CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V`. `CONTROL.DATASET_OBSERVABILITY_V` remains the one cross-execution-model surface and exposes only compact Dynamic Table triage fields.

A currently executing refresh takes precedence over the previous completed refresh when deriving `SILVER_STATUS = RUNNING`. The Framework does not map Dynamic Table refresh statistics into the explicit-pipeline `ROWS_AFFECTED` contract because their semantics differ.

The core operational path remains database-local Information Schema. Account Usage can serve separate long-retention reporting when required, but is not substituted into low-latency domain health merely for longer history. See `docs/architecture/DYNAMIC_TABLE_OBSERVABILITY.md`.

## Canonical explicit-pipeline run metrics — 0.20

Migration `110_pipeline_execution_metrics.sql` established:

```text
ROWS_AFFECTED = SQLROWCOUNT for the primary Silver DML
DML_QUERY_ID  = SQLID captured immediately after that same DML
```

Pattern-specific physical work belongs in `METRICS`; historical inserted/updated/deleted columns are compatibility evidence only. See `docs/architecture/RUN_EVIDENCE.md`.

## Release readiness — 0.21

Migration `120_release_readiness.sql` plus generated release bundles enforce active/candidate invariants, runtime/DQ/comparison freshness, hard preflight/postflight, `CONTROL.RELEASE_RUN` audit, grant-preserving cutover and guarded rollback.

`BLOCKED` has no bypass. `REVIEW_REQUIRED` requires explicit acceptance and reason. `CANDIDATE_VERSION` remains the current single-candidate convenience/lock; do not invent a speculative lifecycle state machine.

## Template provenance — 0.22

New implementation versions declare deterministic `framework_version`, `template_id`, `template_revision`, and `template_digest`. `esf upgrade-plan` is read-only. Pre-provenance versions are `UNKNOWN`; digest mismatch is `UNVERIFIED`; historical template revision is never guessed from SQL.

0.25 changes only project-level Control migration content. Dataset scaffold artifact contracts did not change, so template revisions do **not** advance for 0.25. See `docs/architecture/TEMPLATE_PROVENANCE.md`.

## Unified observability boundary

Unify evidence contracts, not runtime mechanics:

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

Do not create fake Dynamic Table `PIPELINE_RUN` rows or another competing unified execution-health abstraction.

## Control Plane migrations

Fresh 0.25 projects include:

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

## Enterprise monitoring

Each domain owns writable Control state and exposes stable read-only health exports:

```text
CONTROL.ENTERPRISE_HEALTH_EXPORT_V
CONTROL.DOMAIN_HEALTH_SUMMARY_V
```

Cross-domain monitoring is read-only aggregation. It does not write back into domain Control.

## dbt / Gold / Semantic

dbt begins at trusted Silver and owns downstream Gold/Mart/Semantic transformation. It never becomes the Bronze-to-Silver execution engine.

## Roadmap state after 0.25

The planned architecture prompts through Dynamic Table observability enrichment are complete. Do **not** add speculative framework abstractions simply to continue the roadmap.

Next changes should be evidence-driven: real Snowflake certification/integration findings, a concrete domain adoption defect, or an operational requirement that cannot fit the existing contracts. Prefer fixing the narrow missing contract over adding a second framework layer.
