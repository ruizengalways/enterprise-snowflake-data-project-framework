# Current context

This file describes the **current architecture**, not a chronological PR log. For a new conversation, read `docs/NEXT_CHAT_HANDOFF.md` first, then this file and the architecture document most relevant to the task.

## Current Framework release identity

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.24.0
```

Always re-check current `main`, open PRs and CI before modifying code. Green static CI is not Snowflake certification. A revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

## Framework boundary

This repository is a developer toolkit/bootstrapper for readable Snowflake domain repositories. It generates explicit source code, validates contracts and provides operational/deployment guardrails. It is **not** a universal runtime interpreter.

Generated implementation and operation units are created once, committed, reviewed and then domain-owned. Framework upgrades never rewrite existing domain implementation SQL in place.

The Framework deliberately does not own source profiling/discovery, one universal ingestion engine, runtime metadata-to-SQL routing, a central SCD engine, business-DQ inference, autonomous production repair, or Bronze-to-Silver execution through dbt.

## Domain and schema boundary

One business domain normally owns one independent repository and one domain database per environment:

```text
enterprise-snowflake-transport-analytics
  -> DEV_TRANSPORT
  -> UAT_TRANSPORT
  -> PROD_TRANSPORT
```

A domain may contain many source systems. Source boundaries remain explicit in repository paths and Snowflake object names.

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

Logical vocabulary and physical identifiers are intentionally separate. `Control` is cross-cutting operational state/evidence, not a medallion transformation layer. Each domain owns its writable `CONTROL` schema; cross-domain monitoring aggregates read-only exports rather than writing to one shared runtime control database. See `docs/architecture/NAMING_AND_LAYERS.md`.

## RAW / ingestion / Bronze

RAW contracts are reviewed engineering declarations. The Framework never infers business keys, ordering/timestamps, CDC/delete semantics, capture fidelity or SCD pattern from source metadata.

Intended flow:

```text
source evidence / engineering judgement
  -> esf raw-contract-draft
  -> engineer review
  -> esf raw-contract-finalize
  -> esf add-dataset
  -> esf plan / scaffold-preview / scaffold
```

Ingestion remains source-specific. Bronze is the retained replay/audit evidence boundary. `CONTROL.INGESTION_RUN` is optional normalized evidence and does not replace connector-native checkpoints.

## Logical pattern vs execution model

Logical semantics and implementation technology remain separate:

```text
pattern
  append | full_refresh | scd1 | scd2 | custom

execution_model
  stream_task | dynamic_table | batch_sql | custom
```

The source manifest stores semantic `pattern` and `raw_contract`. Implementation technology and version-local execution policy live in `version.yml`.

Supported matrix remains deliberately narrow:

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

A new `stream_task` implementation declares its Task warehouse in version-local `task:` metadata and may explicitly opt into:

```text
minimum_trigger_interval_seconds -> USER_TASK_MINIMUM_TRIGGER_INTERVAL_IN_SECONDS
timeout_seconds                  -> USER_TASK_TIMEOUT_MS
suspend_after_failures           -> SUSPEND_TASK_AFTER_NUM_FAILURES
error_integration                -> ERROR_INTEGRATION
warehouse                        -> WAREHOUSE
```

Optional Task settings are omitted when unspecified, so Snowflake defaults remain in effect. Minimum trigger interval is accepted only for generated Stream-triggered `append`, `scd1` and `scd2`; `full_refresh + stream_task` fails closed because its generated Task has no Stream readiness condition.

The Framework deliberately does not expose arbitrary schedules, generic `AFTER` graph wiring, `TASK_AUTO_RETRY_ATTEMPTS`, a universal readiness DSL, or a general orchestration framework.

Pre-0.23 Stream/Task versions without a `task:` block remain valid. Stream/Task template provenance revision 1 remains immutable; the current generated Stream/Task contract is revision 2. See `docs/architecture/TASK_OPERATIONAL_CONFIG.md`.

## Dynamic Table Silver

Dynamic Table remains first-class for compatible declarative patterns. A Dynamic Table implementation intentionally has no fake Stream, Task, apply or replay procedure files.

Version-local Dynamic Table settings remain:

```text
target_lag
warehouse
refresh_mode = incremental | full
```

`TARGET_LAG` is execution policy, not logical SLA. Dynamic Table execution evidence stays Snowflake-native rather than creating fake `CONTROL.PIPELINE_RUN` rows.

## Canonical explicit-pipeline run metrics — 0.20

Migration `110_pipeline_execution_metrics.sql` introduced the stable explicit-run metrics contract:

```text
METRICS_CONTRACT_VERSION
ROWS_READ
ROWS_AFFECTED
AFFECTED_BUSINESS_KEYS
DML_QUERY_ID
METRICS VARIANT
```

Canonical invariant:

```text
ROWS_AFFECTED = SQLROWCOUNT for the primary Silver DML
DML_QUERY_ID  = SQLID captured immediately after that same DML
```

Pattern-specific work belongs in `METRICS`. Historical insert/update/delete fields remain compatibility evidence, not one cross-pattern semantic contract. See `docs/architecture/RUN_EVIDENCE.md`.

## Release readiness — 0.21

Migration `120_release_readiness.sql` and the generated release bundle enforce fail-closed candidate release/rollback:

```text
candidate deploy
  -> bootstrap / refresh
  -> catch up
  -> DQ
  -> active-vs-candidate comparison
  -> hard preflight
  -> explicit cutover
  -> hard postflight
  -> CONTROL.RELEASE_RUN audit
  -> guarded rollback if required
```

`BLOCKED` has no bypass. `REVIEW_REQUIRED` requires explicit operator acceptance and a reason. `CANDIDATE_VERSION` remains a single-candidate convenience/lock; do not replace it with a speculative large lifecycle state machine until real operations own each transition.

Stable published view replacement happens only at explicit release/rollback boundaries and preserves grants with `COPY GRANTS`.

## Template provenance — 0.22

Every newly scaffolded implementation version declares deterministic provenance:

```text
framework_version
template_id
template_revision
template_digest
```

`esf upgrade-plan --project-root .` is read-only and reports `CURRENT`, `UPDATE_AVAILABLE`, `ADVISORY`, `UNKNOWN` or `UNVERIFIED`.

Pre-provenance versions are `UNKNOWN`; the Framework never inspects generated SQL to infer their historical template revision. Digest mismatch is `UNVERIFIED`. Existing domain-owned code is never rewritten. See `docs/architecture/TEMPLATE_PROVENANCE.md`.

## Domain health evaluation cadence — 0.24

Released migration `040_health_task.sql` historically created `CONTROL.EVALUATE_DOMAIN_HEALTH_TASK` with `SCHEDULE = '1 MINUTE'`. That migration remains immutable.

Framework 0.24 adds:

```text
130_health_evaluation_cadence.sql
CONTROL.HEALTH_EVALUATION_CHANGE
CONTROL.HEALTH_EVALUATION_CONFIG_V
esf health-cadence-sql
operations/health/<operation_id>/
```

Migration 130 performs **no `ALTER TASK`**. Upgrading the Framework therefore never changes a running domain's cadence.

A cadence change is a separate reviewed domain operation. The supported interval contract is `10..691200` seconds. The operator must explicitly choose the final Task state with either `--resume-after` or `--leave-suspended`.

Generated operation order is:

```text
hard duplicate-operation guard
  -> write STARTED audit evidence
  -> ALTER TASK ... SUSPEND
  -> ALTER TASK ... SET SCHEDULE = '<N> SECONDS'
  -> optional explicit RESUME
  -> mark audit SUCCEEDED
```

If Task DDL fails after `STARTED`, the incomplete audit row remains as partial-operation evidence. The Framework does not blindly retry it. Preflight/postflight use `SHOW TASKS` to verify actual Snowflake schedule/state; `HEALTH_EVALUATION_CONFIG_V` is only the latest successfully **recorded Framework operation**, not a claim about out-of-band edits.

Health evaluator cadence is domain operational policy, not dataset SLA. It is not added to `config/project.yml`, source manifests, or dataset version metadata. See `docs/architecture/HEALTH_EVALUATION_CADENCE.md`.

## Unified observability boundary

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

Do not create fake Dynamic Table `PIPELINE_RUN` rows or a second competing unified Silver health abstraction without a concrete missing contract.

## Control Plane migrations

Fresh 0.24 projects include:

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

Released numbered migrations are immutable. Future corrections/features append a later migration; never edit 001..130 in place after release.

Rerunning `esf init-project` materializes newly introduced missing Framework files but never rewrites an existing domain-owned `control_plane/deploy_manifest.txt`. Engineers review `esf control-plan` and explicitly append adopted migrations without reordering already-recorded history.

## Apply-once deployment and DDL safety

CONTROL and SILVER manifests are environment-local apply-once histories:

```text
NEW path                        -> APPLY
recorded + same checksum/order  -> SKIP
checksum/path/order drift       -> BLOCK
unresolved STARTED/FAILED       -> BLOCK
```

New persistent version-owned objects are create-only/fail-closed. Snowflake DDL is not treated as one rollbackable cross-object transaction; partial changes require inspection and explicit correction.

## DQ / reconciliation / SLA

Dataset-local structural validation writes `CONTROL.DQ_RESULT`. Domain-authored reconciliation can write `CONTROL.RECONCILIATION_RESULT`. Candidate evidence remains version-specific and isolated from active production health.

SLA remains logical-dataset policy. Do not infer SLA thresholds from Dynamic Table target lag, version Task configuration, or domain health evaluator cadence.

## Enterprise monitoring

Each domain owns writable Control state and exposes stable read-only health exports:

```text
CONTROL.ENTERPRISE_HEALTH_EXPORT_V
CONTROL.DOMAIN_HEALTH_SUMMARY_V
```

Enterprise monitoring may aggregate these exports but does not write to domain Control or reinterpret domain SLA/DQ logic.

## dbt / Gold / Semantic

dbt begins at trusted Silver and owns downstream Gold/Mart/Semantic transformation. It never becomes the Bronze-to-Silver execution engine in this Framework.

## Immediate next implementation priority

After metrics correctness (0.20), release hardening (0.21), provenance (0.22), Task operational policy (0.23), and configurable domain health cadence (0.24), the remaining roadmap item is deliberately narrow:

```text
Prompt 6 — Dynamic Table observability enrichment

migration 100 already provides the native evidence path
health already consumes CONTROL.DATASET_OBSERVABILITY_V

only add concrete missing Snowflake-native evidence that improves operations
for example refresh action/trigger, target lag, state code/message, statistics or query id

do not create another unified execution-health abstraction
do not insert fake PIPELINE_RUN rows
```

Before changing migration 100 or any released migration, remember that all released numbered migrations are immutable. Any enrichment must be a later migration.
