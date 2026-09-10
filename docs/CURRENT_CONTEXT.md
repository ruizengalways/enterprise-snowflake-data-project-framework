# Current context

This file describes the **current architecture**, not a chronological PR log. For a new conversation, read `docs/NEXT_CHAT_HANDOFF.md` first, then this file and the architecture document most relevant to the task.

## Stable baseline

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.22.0
0.22 code merge = ee6044db2b0f0e1b67ee929fecacdcc0080520bd
PR #32     = merged: template provenance + read-only upgrade planning
PR CI #287 = SUCCESS
main CI #288 = SUCCESS
Snowflake Framework Certification #44 = SKIPPED
```

The certification workflow skip is intentional while the trusted Snowflake environment is disabled/unconfigured. **No 0.22.0 SHA has produced a real `status = CERTIFIED` Snowflake artifact.** Green static CI is not Snowflake certification.

## Framework position

This repository is a developer toolkit/bootstrapper for readable enterprise Snowflake domain repositories. It generates explicit source code, validates contracts and supplies operational/deployment guardrails. It is **not** a universal runtime interpreter.

The Framework deliberately does not own source profiling/discovery, a universal ingestion engine, runtime metadata-to-SQL routing, one central SCD engine, business-DQ inference, autonomous production repair, or Bronze-to-Silver execution through dbt.

Generated ownership units are created once, committed, reviewed and then domain-owned.

## Domain and schema boundary

One business domain normally owns one independent repository and one domain database per environment:

```text
enterprise-snowflake-transport-analytics
  -> DEV_TRANSPORT
  -> UAT_TRANSPORT
  -> PROD_TRANSPORT
```

A domain may contain many source systems. Source boundaries stay explicit in repository paths and object names.

Canonical **logical architecture vocabulary** is:

```text
Bronze
Silver
Gold / Marts
Semantic
Control
```

Default **physical Snowflake schemas** are:

```text
BRONZE
SILVER
GOLD_MARTS
SEMANTIC
CONTROL
```

Logical vocabulary and physical names are intentionally not forced to be identical. In particular, do not rename `GOLD_MARTS` to `GOLD` merely to make prose match identifiers. `Control` is cross-cutting operational evidence/state, not a medallion transformation layer.

Each domain owns its writable `CONTROL` schema. Cross-domain observability is read-only aggregation; never replace this with one enterprise-wide writable runtime control database. See `docs/architecture/NAMING_AND_LAYERS.md`.

## RAW / ingestion / Bronze

RAW contracts are reviewed engineering declarations. The Framework never infers business keys, timestamps/order, CDC/delete semantics or SCD pattern from source metadata.

Intended authoring flow:

```text
source evidence / engineering judgement
  -> esf raw-contract-draft
  -> engineer review
  -> esf raw-contract-finalize
  -> esf add-dataset
  -> esf plan / scaffold-preview / scaffold
```

Source profiling/discovery remains outside this Framework. Ingestion remains source-specific: Openflow, Snowpipe, Kafka, API/ETL/orchestrators or other technology can coexist. Bronze is the retained replay/audit evidence boundary.

`CONTROL.INGESTION_RUN` is optional normalized run evidence; it does not replace connector-native checkpoints.

## Logical pattern vs execution model

Dataset semantics and implementation technology are separate concepts.

Logical pattern:

```text
append
full_refresh
scd1
scd2
custom
```

Version-level execution model:

```text
stream_task
dynamic_table
batch_sql
custom
```

`pattern` remains in the source manifest and logical `CONTROL.DATASET`. `execution_model` belongs to `version.yml` and `CONTROL.DATASET_VERSION`. `procedure` is not a peer execution model; it is an implementation artifact.

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

Unsupported combinations fail closed, including `scd2 + dynamic_table` and `append + dynamic_table`. See `docs/architecture/EXECUTION_MODELS.md`.

## Generated Silver ownership

The default standard implementation remains Snowflake-native readiness + explicit dataset-local SQL/procedure, with Task execution where appropriate.

Typical Stream/Task ownership unit:

```text
version.yml
001_objects.sql
010_apply.sql
015_replay.sql
020_validate.sql
025_compare.sql
030_task.sql
040_register.sql
050_publish.sql
060_policy.sql
deploy_manifest.fragment.txt
```

A generated Task executes dataset-local apply and validation procedures. Persistent version-owned objects are create-only/fail-closed.

SCD1 current-state mutation is ordering-aware when the RAW contract has ordering evidence: only a strictly newer tuple may update/delete an existing key. Equal tuples are duplicate/no-op and older late arrivals cannot regress current state.

SCD2 retains event evidence and deterministic versioned history; late evidence rebuilds affected business-key history.

## Dynamic Table Silver

Dynamic Table is first-class for compatible declarative patterns. A Dynamic Table implementation intentionally has no fake Stream, Task, apply or replay procedure files.

For `scd1 + dynamic_table`, current state is defined declaratively from Bronze using business key, reviewed ordering and tombstone semantics. For `full_refresh + dynamic_table`, the Dynamic Table represents the current Bronze snapshot.

Version-local settings are currently:

```text
target_lag
warehouse
refresh_mode = incremental | full
```

`TARGET_LAG` is execution policy, not logical SLA. The Framework does not default to refresh mode `AUTO`.

Dynamic Table DQ remains explicit dataset-local SQL writing `CONTROL.DQ_RESULT`. Runtime evidence remains Snowflake-native refresh history rather than fake `CONTROL.PIPELINE_RUN` rows.

## Canonical explicit-pipeline run metrics

Framework 0.20 corrected the semantics of `CONTROL.PIPELINE_RUN` for new generated explicit apply procedures. Control migration `110_pipeline_execution_metrics.sql` introduced metrics contract version 1:

```text
METRICS_CONTRACT_VERSION
ROWS_READ
ROWS_AFFECTED
AFFECTED_BUSINESS_KEYS
DML_QUERY_ID
METRICS VARIANT
```

Existing `SILVER_DATA_MAX_AT`, `SILVER_PUBLISHED_AT`, status/timestamps/error fields remain timing/result evidence.

Canonical invariant:

```text
ROWS_AFFECTED = SQLROWCOUNT for the primary Silver DML
DML_QUERY_ID  = SQLID captured immediately after that same DML
```

Pattern-specific work belongs inside `METRICS`; the original `ROWS_INSERTED`, `ROWS_UPDATED`, `ROWS_DELETED` fields remain only for historical compatibility and are not a cross-pattern contract.

`CONTROL.PIPELINE_EXECUTION_METRICS_V` is the stable canonical read surface. Because dataset SQL is generated once/domain-owned, migration 110 does not rewrite old procedures. See `docs/architecture/RUN_EVIDENCE.md`.

## Unified observability boundary

Unify evidence contracts, not runtime mechanics:

```text
explicit apply execution
  -> CONTROL.PIPELINE_RUN
  -> CONTROL.PIPELINE_EXECUTION_METRICS_V

Dynamic Table execution
  -> INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V

both active execution models
  -> CONTROL.DATASET_OBSERVABILITY_V
  -> CONTROL.DATASET_HEALTH / SLA / incidents
```

Do not create fake pipeline runs for Dynamic Tables or a second competing unified Silver health layer without a concrete need.

## Control Plane migrations

Fresh 0.22 projects include:

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

Released numbered migrations are immutable. Future corrections/features append later migrations; never modify 001..120 in place after release.

Key later migrations:

```text
090 -> version execution model / primary runtime identity
100 -> Dynamic Table native observability normalization
110 -> canonical explicit-pipeline execution metrics
120 -> release readiness, version invariants and release audit surfaces
```

Rerunning `init-project` materializes missing newly introduced files but never rewrites an existing domain-owned deploy manifest or generated implementation SQL. Engineers review `esf control-plan` and append adopted migrations without reordering already-recorded migration history.

## Apply-once deployment

CONTROL and SILVER manifests are environment-local migration histories, not replay lists.

```text
NEW path                        -> APPLY
recorded + same checksum/order  -> SKIP
checksum/path/order drift       -> BLOCK
unresolved STARTED/FAILED       -> BLOCK
```

`CONTROL.DEPLOYMENT_HISTORY` records exact-file SHA-256, manifest position, project/framework Git SHA, status/timestamps/errors and GitHub run metadata.

Existing populated domains with empty history require explicit baseline adoption of the exact already-deployed revision. Failed/partial migrations require reviewed remediation; no automatic retry.

Normal deployments serialize per domain/environment. dbt remains desired-state and may run every deployment.

## DDL / publication safety

New persistent version-owned tables, streams, views, procedures, tasks and Dynamic Tables are create-only. Unexpected pre-existing names are ownership conflicts.

Initial stable published views are create-only. Candidate deployment does not alter stable consumer objects.

Explicit release/rollback is the generated replacement boundary using:

```text
CREATE OR REPLACE VIEW ... COPY GRANTS
```

Snowflake DDL is not treated as one rollbackable cross-object transaction; release operations therefore use explicit preflight, cutover, postflight, audit and guarded rollback.

## Candidate / release / rollback

Candidates live under:

```text
silver_processing/<source>/<dataset>/versions/vN/
```

Creating v2 changes zero bytes in v1.

Current intended path:

```text
scaffold candidate
  -> append migrations
  -> deploy once
  -> bootstrap/replay/refresh
  -> catch up
  -> DQ
  -> active-vs-candidate comparison
  -> hard preflight
  -> explicit cutover
  -> hard postflight
  -> RELEASE_RUN audit
  -> guarded rollback if required
```

Framework 0.21 added `120_release_readiness.sql` and hardened this boundary:

- `ACTIVE_VERSION` must match the requested release `from_version`.
- `CANDIDATE_VERSION` remains a convenience/single-candidate lock and cannot be silently overwritten by another candidate.
- Candidate and active versions must differ and version status/pointers must remain synchronized.
- Readiness consumes latest candidate runtime, DQ and active-vs-candidate comparison evidence.
- Comparison freshness uses the oldest timestamp among each check's latest evidence, so rerunning one check cannot hide another stale check.
- `BLOCKED` has no bypass. `REVIEW_REQUIRED` needs explicit `--allow-review-required --reason ...` acceptance.
- Hard preflight occurs after candidate catch-up/DQ/compare; `activate.sql` does not refresh/resume the candidate after that gate and thereby invalidate reviewed evidence.
- Cutover preserves stable view grants with `COPY GRANTS`; postflight checks the intended object/version boundary precisely.
- `CONTROL.RELEASE_RUN` records activate/rollback phase, operator reason, errors and pre/postflight status.
- Rollback is fail-closed: target catch-up/runtime/DQ evidence must be current enough, and a newer candidate cycle blocks stale rollback.

`esf release-sql` emits a fixed review bundle:

```text
README.md
preflight.sql
activate.sql
rollback.sql
postflight.sql
```

The Framework still does not execute the production cutover automatically. Keep `CANDIDATE_VERSION` for now; do not invent a speculative large DEVELOPMENT/BOOTSTRAPPING/SHADOW/VALIDATED state machine until real operations own those transitions.

## Template provenance and upgrade planning

Framework 0.22 adds generation provenance to every newly scaffolded `version.yml`:

```text
framework_version
template_id
template_revision
template_digest
```

The immutable compatibility identity is template id + revision + digest. Generation deliberately has no timestamp-dependent provenance field, so output stays deterministic.

`esf upgrade-plan --project-root .` is read-only. It can report:

```text
CURRENT
UPDATE_AVAILABLE
ADVISORY
UNKNOWN
UNVERIFIED
```

Pre-0.22 versions without provenance remain valid and report `UNKNOWN`; the Framework **never inspects SQL to guess their template revision**. A digest mismatch reports `UNVERIFIED`. Existing domain-owned code is never rewritten by the plan. See `docs/architecture/TEMPLATE_PROVENANCE.md`.

## DQ / reconciliation / SLA

Dataset-local structural validation writes `CONTROL.DQ_RESULT`. Domain-authored reconciliation can write `CONTROL.RECONCILIATION_RESULT`. Candidate evidence remains version-specific and isolated from active production health.

SLA remains logical-dataset policy, separate from source manifest and execution technology. Do not infer thresholds from Dynamic Table target lag or Task timing configuration.

Health evaluator Tasks are currently serverless and created suspended. The legacy released `040_health_task.sql` contains a one-minute schedule; configurable health cadence must be introduced through a **new later migration/configuration mechanism**, never by editing 040.

## Enterprise monitoring

Each domain owns writable CONTROL state and exposes stable read-only health exports:

```text
CONTROL.ENTERPRISE_HEALTH_EXPORT_V
CONTROL.DOMAIN_HEALTH_SUMMARY_V
```

Enterprise monitoring may aggregate these exports but does not write to domain CONTROL or reinterpret domain SLA/DQ logic.

## dbt / Gold / Semantic

dbt begins at trusted Silver and owns downstream Gold/Mart/Semantic transformation. It never becomes the Bronze-to-Silver execution engine in this Framework.

## Trusted real-Snowflake certification

Credential-free PR/main CI covers package installation, released-migration immutability, reference validation, dbt parse, unit/contracts and runtime-indirection guardrails.

Full certification is only from the trusted Snowflake boundary. A Framework revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

For the current 0.22 code merge, main CI #288 is green and Snowflake Framework Certification #44 is `SKIPPED`, so live acceptance remains outstanding.

## Immediate next implementation priority

After metrics correctness (0.20), release hardening (0.21), provenance/upgrade planning (0.22) and documentation contract cleanup, continue in this order unless live Snowflake evidence changes priorities:

```text
1. narrow Task operational configuration (Prompt 10)
   support first:
     minimum trigger interval
     timeout
     suspend after failures
     warehouse override
     optional error integration
   do not add:
     generic graph retry
     arbitrary schedules
     universal readiness/orchestration DSL

2. configurable domain health evaluation interval (Prompt 11)
   add a NEW migration/configuration mechanism
   never edit released 040_health_task.sql

3. Dynamic Table observability enrichment (Prompt 6)
   only if concrete native evidence is still missing
   enrich CONTROL.DATASET_OBSERVABILITY_V path rather than adding a second unified abstraction
```

The next feature should remain version-local and generated-once. Task operational settings are execution policy, not logical dataset/SLA metadata.
