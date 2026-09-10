# Current context

This file describes the **current architecture**, not a chronological PR log. For a new conversation, read `docs/NEXT_CHAT_HANDOFF.md` first, then this file.

## Stable baseline

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.20.0
0.20 code merge = 8647190c175d4c6b815e46eb78574aea475a5040
PR #29     = merged
PR CI #263 = SUCCESS
main CI #264 = SUCCESS
Snowflake Framework Certification run #20 = SKIPPED
```

The documentation itself may be merged after the code SHA above, so always query current `main` before modifying the repository. The certification workflow skip is intentional while the trusted Snowflake environment is disabled/unconfigured. No 0.20.0 SHA has yet produced a real `status = CERTIFIED` artifact. Green static CI is not Snowflake certification.

## Framework position

This repository is a developer toolkit/bootstrapper for readable enterprise Snowflake domain repositories. It generates explicit source code, validates contracts and provides operational/deployment guardrails. It is **not** a universal runtime interpreter.

The Framework deliberately does not own source profiling/discovery, a universal ingestion engine, runtime metadata-to-SQL routing, one central SCD engine, business-DQ inference, autonomous production repair, or Bronze-to-Silver execution through dbt.

Generated ownership units are created once, committed, reviewed and then domain-owned.

## Domain boundary

One business domain normally owns one independent repository and one domain database per environment:

```text
enterprise-snowflake-transport-analytics
  -> DEV_TRANSPORT
  -> UAT_TRANSPORT
  -> PROD_TRANSPORT
```

A domain may contain many source systems. Source boundaries stay explicit in repository paths and object names. A typical domain database uses:

```text
BRONZE
SILVER
GOLD_MARTS
SEMANTIC
CONTROL
```

Each domain owns its writable `CONTROL` schema. Cross-domain observability is read-only aggregation; never replace this with one enterprise-wide writable runtime control database.

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

Source profiling/discovery remains outside this Framework. Ingestion remains source-specific: Openflow, Snowpipe, Kafka, API/ETL/orchestrators or other technology can be used. Bronze is the retained replay/audit evidence boundary.

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

Unsupported combinations fail closed, including `scd2 + dynamic_table` and `append + dynamic_table`.

See `docs/architecture/EXECUTION_MODELS.md`.

## Stream + Task Silver

The default standard implementation remains Snowflake-native Stream/readiness + Task + explicit dataset-local SQL/procedure.

Typical ownership unit:

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

A generated Task executes the dataset-local apply and validation procedures. Persistent version-owned objects are create-only/fail-closed.

SCD1 current-state mutation is ordering-aware when the RAW contract has ordering evidence: only a strictly newer tuple may update/delete an existing key. Equal tuples are duplicate/no-op and older late arrivals cannot regress current state.

SCD2 retains event evidence and deterministic versioned history; late evidence rebuilds affected business-key history.

## Dynamic Table Silver

Dynamic Table is first-class for compatible declarative patterns. A Dynamic Table implementation intentionally has no fake Stream, Task, apply or replay procedure files.

For `scd1 + dynamic_table`, current state is defined declaratively from Bronze using business key, reviewed ordering and tombstone semantics. For `full_refresh + dynamic_table`, the Dynamic Table represents the current Bronze snapshot.

Version-local settings are:

```text
target_lag
warehouse
refresh_mode = incremental | full
```

`TARGET_LAG` is execution policy, not logical SLA. The Framework does not default to refresh mode `AUTO`.

Dynamic Table DQ remains explicit dataset-local SQL writing `CONTROL.DQ_RESULT`. Runtime evidence remains Snowflake-native refresh history rather than fake `CONTROL.PIPELINE_RUN` rows.

## Canonical explicit-pipeline run metrics

0.20 fixes the semantics of `CONTROL.PIPELINE_RUN` for new generated explicit apply procedures.

Older generated implementations could assign Snowflake `SQLROWCOUNT` after a `MERGE` into `ROWS_UPDATED`, even though `SQLROWCOUNT` represents total rows affected by that DML. They could also record `LAST_QUERY_ID()` during later success logging rather than capture the transformation DML id immediately.

Control migration 110 introduces metrics contract version 1:

```text
METRICS_CONTRACT_VERSION
ROWS_READ
ROWS_AFFECTED
AFFECTED_BUSINESS_KEYS
DML_QUERY_ID
METRICS VARIANT
```

Existing `SILVER_DATA_MAX_AT`, `SILVER_PUBLISHED_AT`, status/timestamps/error fields remain the timing and result evidence.

Canonical invariant:

```text
ROWS_AFFECTED = SQLROWCOUNT for the primary Silver DML
DML_QUERY_ID  = SQLID captured immediately after that same DML
```

Pattern-specific work is explicit inside `METRICS`:

```text
append       -> output_rows_inserted
full_refresh -> snapshot_rows_written
scd1         -> merge_rows_affected
scd2         -> events_inserted
                history_rows_deleted
                history_rows_rebuilt
                query ids for those important DML statements
```

The original `ROWS_INSERTED`, `ROWS_UPDATED`, `ROWS_DELETED` columns remain for historical compatibility but are no longer treated as one cross-pattern contract. New SCD1/SCD2 generated code leaves misleading breakdowns NULL rather than inventing precision.

`CONTROL.PIPELINE_EXECUTION_METRICS_V` is the stable canonical read surface for explicit-run metrics and exposes legacy row fields with `LEGACY_` prefixes for audit.

Because dataset SQL is generated once/domain-owned, 110 does not rewrite old procedures. Old implementations retain their historical metric behavior until manually migrated or replaced by a reviewed candidate version.

See `docs/architecture/RUN_EVIDENCE.md`.

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

Fresh 0.20 projects include:

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
```

Released numbered migrations are immutable. Future corrections/features append later migrations; never modify 001..110 in place after release.

090 adds `EXECUTION_MODEL` / `PRIMARY_RUNTIME_OBJECT`. 100 normalizes Dynamic Table native refresh evidence. 110 adds canonical explicit-pipeline metrics.

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

Old runtime processing is retired last. Snowflake DDL is not treated as one rollbackable cross-object transaction; partial release requires inspection and explicit rollback/correction.

## Candidate / release / repair

Candidates live under:

```text
silver_processing/<source>/<dataset>/versions/vN/
```

Creating v2 changes zero bytes in v1.

Typical path:

```text
scaffold candidate
  -> append migrations
  -> deploy once
  -> bootstrap/replay/refresh
  -> catch up
  -> DQ
  -> active-vs-candidate comparison
  -> explicit release operation
  -> cutover
```

Release/lifecycle/repair are execution-model aware. Supported cross-model example: SCD1 v1 `stream_task` -> v2 `dynamic_table`.

Current state contains both `CONTROL.DATASET.ACTIVE_VERSION`, `CONTROL.DATASET.CANDIDATE_VERSION`, and per-version `STATUS`. The next release-hardening work should enforce strict active/candidate invariants before considering removal of the convenience candidate pointer. Do not invent a large lifecycle state machine until real operations own every transition.

## DQ / reconciliation / SLA

Dataset-local structural validation writes `CONTROL.DQ_RESULT`. Domain-authored reconciliation can write `CONTROL.RECONCILIATION_RESULT`. Candidate evidence remains version-specific and isolated from active production health.

SLA remains logical-dataset policy, separate from source manifest and execution technology. Do not infer thresholds from Dynamic Table target lag or Task timing configuration.

Health evaluator Tasks are currently serverless and created suspended. The legacy released 040 health-task migration contains a one-minute schedule; if cadence becomes configurable later, implement that through a new migration/configuration mechanism rather than editing 040.

## Enterprise monitoring

Each domain owns its writable CONTROL state and exposes stable read-only health exports:

```text
CONTROL.ENTERPRISE_HEALTH_EXPORT_V
CONTROL.DOMAIN_HEALTH_SUMMARY_V
```

Enterprise monitoring may aggregate these exports but does not write to domain CONTROL or reinterpret domain SLA/DQ logic.

## dbt / Gold / Semantic

dbt begins at trusted Silver and owns downstream Gold/Mart/Semantic transformation. It never becomes the Bronze-to-Silver execution engine in this Framework.

## Trusted real-Snowflake certification

Credential-free PR/main CI covers package installation, released-migration immutability, reference validation, dbt parse, unit/contracts and runtime-indirection guardrails.

Full certification is only from the trusted Snowflake boundary:

```text
CI_FRAMEWORK_CERT
AR_FRAMEWORK_CERT
AR_FRAMEWORK_CERT_READER
SU_GITHUB_FRAMEWORK_CERT
WH_FRAMEWORK_CERT_TRANSFORM
```

Canonical live scenarios cover APPEND/SCD1/SCD2/FULL_REFRESH, Stream/Task execution, Dynamic Table cross-model upgrade, DQ, migration replay/drift/failure protection, candidate bootstrap/catch-up, grant-preserving cutover and rollback.

A Framework revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA. For the 0.20 code merge the workflow was created and safely skipped because live certification remains disabled/unconfigured.

## Immediate next implementation priority

After 0.20 metrics correctness, the next feature should harden candidate release without overbuilding state management:

```text
release preflight
  -> verify expected active version
  -> verify one intended candidate / no conflict
  -> verify candidate objects/runtime evidence
  -> verify DQ + version comparison evidence and freshness
  -> fail before mutation on inconsistency

explicit cutover
  -> existing execution-model-aware publication/runtime switch

release postflight
  -> verify stable published objects, CONTROL pointers and runtime state

CONTROL.RELEASE_RUN
  -> auditable attempt/status/error record
```

Retain `CANDIDATE_VERSION` initially but enforce single-active/single-candidate synchronization invariants. Do not replace it immediately with a speculative DEVELOPMENT/DEPLOYED/BOOTSTRAPPING/SHADOW/VALIDATED state machine.

After release hardening, priorities are template provenance + read-only `upgrade-plan`, documentation vocabulary consistency, narrow Task operational configuration, configurable health cadence through a new migration, and only then Dynamic Table observability enrichment if concrete evidence remains missing.
