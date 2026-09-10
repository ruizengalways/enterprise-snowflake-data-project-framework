# Current context

This file describes the **current architecture**, not a chronological PR log. For a new conversation, read `docs/NEXT_CHAT_HANDOFF.md` first, then this file and the architecture document most relevant to the task.

## Current Framework release identity

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.23.0
```

Always re-check current `main`, open PRs and CI in GitHub before modifying code. Do not encode a green static CI run as Snowflake certification: a revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

## Framework boundary

The repository is a developer toolkit/bootstrapper for readable Snowflake domain repositories. It generates explicit source code, validates contracts and provides operational/deployment guardrails. It is not a universal runtime interpreter.

Generated implementation units are created once, committed, reviewed and then domain-owned. Framework upgrades never rewrite existing domain implementation SQL in place.

## Domain and schema boundary

One business domain normally owns one repository and one domain database per environment. A domain can contain many sources; source identity remains explicit in paths and generated object names.

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

RAW contracts are reviewed engineering declarations. The Framework does not infer business keys, timestamps/order, CDC/delete semantics or SCD pattern from source metadata.

```text
source evidence / engineering judgement
  -> esf raw-contract-draft
  -> engineer review
  -> esf raw-contract-finalize
  -> esf add-dataset
  -> esf plan / scaffold-preview / scaffold
```

Ingestion stays source-specific. Bronze is retained replay/audit evidence. `CONTROL.INGESTION_RUN` is normalized run evidence, not connector checkpoint ownership.

## Pattern vs execution model

Logical pattern:

```text
append | full_refresh | scd1 | scd2 | custom
```

Version execution model:

```text
stream_task | dynamic_table | batch_sql | custom
```

Supported matrix remains intentionally narrow:

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

Task operational settings are **version-local execution policy**. They belong in `version.yml`; they do not belong in the logical source manifest and are not SLA.

A newly generated Stream/Task version declares at least its warehouse:

```yaml
version:
  execution_model: stream_task
  task:
    warehouse: WH_TRANSPORT_TRANSFORM
```

Optional generated settings are deliberately narrow:

```yaml
  task:
    warehouse: WH_TRANSPORT_HEAVY
    minimum_trigger_interval_seconds: 60
    timeout_seconds: 900
    suspend_after_failures: 3
    error_integration: TASK_ERROR_NOTIFICATIONS
```

They map directly to Snowflake Task properties:

```text
warehouse                         -> WAREHOUSE
minimum_trigger_interval_seconds -> USER_TASK_MINIMUM_TRIGGER_INTERVAL_IN_SECONDS
timeout_seconds                  -> USER_TASK_TIMEOUT_MS
suspend_after_failures           -> SUSPEND_TASK_AFTER_NUM_FAILURES
error_integration                -> ERROR_INTEGRATION
```

Unspecified optional properties are omitted, preserving Snowflake defaults rather than inventing Framework-wide runtime policy. Minimum trigger interval is only accepted for actual stream-triggered `append`, `scd1` and `scd2` Task implementations. `full_refresh + stream_task` has no generated Stream readiness signal, so the option fails closed there.

The Framework deliberately does **not** expose arbitrary Task schedules, a generic graph-retry abstraction, `TASK_AUTO_RETRY_ATTEMPTS`, or a universal orchestration/readiness DSL. See `docs/architecture/TASK_OPERATIONAL_CONFIG.md`.

Because this changes Stream/Task generated artifacts, 0.23 advances Stream/Task template provenance from revision 1 to revision 2 while retaining revision 1 in the immutable registry. `esf upgrade-plan` can therefore report older 0.22 Stream/Task implementations as `UPDATE_AVAILABLE` without rewriting them or inventing an advisory.

## Dynamic Table execution

Dynamic Table remains first-class only for compatible declarative patterns. Its version-local settings are:

```text
target_lag
warehouse
refresh_mode = incremental | full
```

Dynamic Table implementations intentionally have no fake Stream/Task/apply/replay artifacts. Runtime evidence comes from Snowflake Dynamic Table refresh history and is normalized into the existing observability boundary.

## Explicit-pipeline metrics — 0.20

`110_pipeline_execution_metrics.sql` introduced the canonical explicit-run metrics contract:

```text
METRICS_CONTRACT_VERSION
ROWS_READ
ROWS_AFFECTED
AFFECTED_BUSINESS_KEYS
DML_QUERY_ID
METRICS VARIANT
```

Invariant:

```text
ROWS_AFFECTED = SQLROWCOUNT for the primary Silver DML
DML_QUERY_ID  = SQLID captured immediately after that same DML
```

Historical `ROWS_INSERTED`, `ROWS_UPDATED`, `ROWS_DELETED` remain compatibility fields only. See `docs/architecture/RUN_EVIDENCE.md`.

## Unified observability

Unify evidence contracts, not runtime mechanics:

```text
explicit apply
  -> CONTROL.PIPELINE_RUN
  -> CONTROL.PIPELINE_EXECUTION_METRICS_V

Dynamic Table
  -> INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V

both
  -> CONTROL.DATASET_OBSERVABILITY_V
  -> health / SLA / incidents
```

Do not create fake Dynamic Table `PIPELINE_RUN` rows or a second competing unified health abstraction.

## Control Plane migrations

Fresh projects include:

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

Released numbered migrations are immutable. Never edit 001..120 in place; append later migrations.

`040_health_task.sql` still contains the historical one-minute evaluator schedule. Configurable health cadence must therefore be introduced by a **new migration/configuration mechanism**, not by editing 040.

## Apply-once deployment and DDL safety

CONTROL and SILVER manifests are migration histories:

```text
new path                         -> APPLY
same applied path/checksum/order -> SKIP
checksum/path/order drift        -> BLOCK
unresolved STARTED/FAILED        -> BLOCK
```

Persistent version-owned objects are create-only/fail-closed. Candidate deployment does not alter stable consumer views. Production view replacement occurs only at the explicit release/rollback boundary and uses `COPY GRANTS`.

## Release readiness — 0.21

`120_release_readiness.sql` and generated release bundles enforce active/candidate invariants and audited cutovers.

```text
candidate deploy
  -> bootstrap / refresh
  -> catch up
  -> DQ
  -> active-vs-candidate compare
  -> hard preflight
  -> activate
  -> hard postflight
  -> CONTROL.RELEASE_RUN audit
  -> guarded rollback if required
```

`BLOCKED` has no bypass. `REVIEW_REQUIRED` requires explicit acceptance and a reason. `CANDIDATE_VERSION` remains a single-candidate convenience/lock; do not invent a large speculative lifecycle state machine until real operations own those transitions.

## Template provenance — 0.22+

New implementation versions declare:

```text
framework_version
template_id
template_revision
template_digest
```

`esf upgrade-plan --project-root .` is read-only and reports `CURRENT`, `UPDATE_AVAILABLE`, `ADVISORY`, `UNKNOWN` or `UNVERIFIED`.

Pre-provenance versions report `UNKNOWN`; the Framework never infers template revision from SQL. Digest mismatch is `UNVERIFIED`. See `docs/architecture/TEMPLATE_PROVENANCE.md`.

## DQ / reconciliation / SLA / enterprise monitoring

Dataset-local structural validation writes `CONTROL.DQ_RESULT`; domain-authored reconciliation writes normalized `CONTROL.RECONCILIATION_RESULT`. Candidate evidence remains version-specific and isolated from active health.

SLA belongs to the logical dataset and stays separate from execution policy such as Task timing or Dynamic Table target lag.

Each domain exposes stable read-only health surfaces for enterprise aggregation; enterprise monitoring does not write to domain Control or reinterpret domain rules.

## dbt

dbt starts at trusted Silver and owns downstream Gold/Mart/Semantic transformation. It is not the Bronze-to-Silver execution engine in this Framework.

## Immediate next implementation priority

After 0.23 Task operational policy, continue in this order unless real Snowflake acceptance evidence changes priorities:

```text
1. Prompt 11 — configurable domain health evaluation interval
   - add a NEW migration/configuration mechanism
   - never edit released 040_health_task.sql
   - support domain-appropriate cadence rather than one global interval

2. Prompt 6 — Dynamic Table observability enrichment
   - first inspect what migration 100 already exposes
   - enrich only concrete missing Snowflake-native evidence
   - keep CONTROL.DATASET_OBSERVABILITY_V as the unified boundary
   - do not create a second unified execution-health abstraction
```
