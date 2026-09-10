# Next chat handoff

Read this file first when continuing the Framework in a new conversation. Then read `docs/CURRENT_CONTEXT.md` and the architecture document most relevant to the task.

## Stable repository state

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.22.0
0.22 code merge = ee6044db2b0f0e1b67ee929fecacdcc0080520bd
merged PR  = #32 feat: add template provenance and read-only upgrade planning
PR CI      = Silver-first Toolkit CI #287 = SUCCESS
main CI    = Silver-first Toolkit CI #288 = SUCCESS
Snowflake Framework Certification #44 = SKIPPED
```

Always re-check current `main`, open PRs and CI before modifying code. The certification skip is intentional while the trusted Snowflake certification environment is not enabled/configured. **No 0.22.0 SHA has yet produced a real `status = CERTIFIED` Snowflake artifact.** Static CI is not Snowflake certification.

## Completed roadmap work

Do not redesign or repeat these completed features unless new evidence identifies a defect.

### 0.20 — canonical explicit-pipeline metrics

`110_pipeline_execution_metrics.sql` corrected misleading `PIPELINE_RUN` row-count/query-id semantics for newly generated explicit apply procedures.

Canonical contract:

```text
METRICS_CONTRACT_VERSION
ROWS_READ
ROWS_AFFECTED
AFFECTED_BUSINESS_KEYS
SILVER_DATA_MAX_AT
SILVER_PUBLISHED_AT
DML_QUERY_ID
METRICS VARIANT
STATUS / timestamps / errors
```

Invariant:

```text
ROWS_AFFECTED = SQLROWCOUNT for the primary Silver DML
DML_QUERY_ID  = SQLID captured immediately after that same DML
```

Do not reintroduce universal insert/update/delete semantics for `MERGE` or mix SCD2 event-ledger work with history rebuild counts. Old `ROWS_INSERTED`, `ROWS_UPDATED`, `ROWS_DELETED` columns remain historical compatibility fields. See `docs/architecture/RUN_EVIDENCE.md`.

### 0.21 — release readiness and active/candidate invariants

`120_release_readiness.sql` and the generated release bundle now enforce fail-closed release/rollback behavior.

Current path:

```text
candidate deploy
  -> bootstrap / refresh
  -> catch up
  -> DQ
  -> active-vs-candidate compare
  -> preflight.sql
  -> activate.sql
  -> postflight.sql
  -> CONTROL.RELEASE_RUN audit
  -> guarded rollback.sql if required
```

Important invariants:

```text
release from_version must equal ACTIVE_VERSION
candidate != active
at most one intended candidate
CANDIDATE_VERSION cannot be silently replaced by another candidate
candidate/runtime/DQ/comparison evidence must be current enough
BLOCKED has no bypass
REVIEW_REQUIRED requires explicit acceptance + reason
postflight verifies published object / CONTROL / runtime state
stale rollback or rollback across a newer candidate cycle fails closed
```

Hard preflight occurs after candidate catch-up/DQ/comparison. `activate.sql` must not refresh/resume the candidate after hard preflight and thereby invalidate reviewed evidence. Stable published views use `CREATE OR REPLACE VIEW ... COPY GRANTS` only at the explicit release/rollback boundary.

Keep `CONTROL.DATASET.CANDIDATE_VERSION` for now as a single-candidate convenience/lock. Do not replace it with a speculative large state machine until real operations own each transition.

### 0.22 — template provenance and read-only upgrade planning

Every newly scaffolded implementation version now declares:

```text
provenance:
  framework_version
  template_id
  template_revision
  template_digest
```

The compatibility identity is immutable template id + revision + digest. No scaffold timestamp is used, so generation remains deterministic.

`esf upgrade-plan --project-root .` is read-only and reports:

```text
CURRENT
UPDATE_AVAILABLE
ADVISORY
UNKNOWN
UNVERIFIED
```

Critical rule: pre-provenance versions report `UNKNOWN`. **Never infer a template revision from SQL, comments, object names or formatting.** Digest mismatch is `UNVERIFIED`, not guessed. The default advisory catalog remains empty until a real released template revision needs an advisory; do not fabricate incidents merely to demonstrate the mechanism. See `docs/architecture/TEMPLATE_PROVENANCE.md`.

## Canonical naming vocabulary

Keep logical architecture vocabulary separate from physical schema naming.

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

Do not bulk-rename `GOLD_MARTS` to `GOLD` for prose consistency. `Control` is cross-cutting operational evidence/state. `PLATFORM_CONTROL` may appear in negative/deprecated explanations such as “do not build a shared writable PLATFORM_CONTROL”; static checks should validate positive canonical contracts rather than grep-ban every occurrence. See `docs/architecture/NAMING_AND_LAYERS.md`.

## Current Control Plane manifest

Fresh 0.22 projects include all of:

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

For an older domain, rerun `esf init-project` to materialize missing Framework files, inspect `esf control-plan`, and explicitly append adopted migrations without reordering already-recorded history. Deployment stays checksum-locked/apply-once.

## Core model that remains stable

Logical semantics and implementation technology remain separate:

```text
logical dataset
  pattern = append | full_refresh | scd1 | scd2 | custom

implementation version
  execution_model = stream_task | dynamic_table | batch_sql | custom
```

The source manifest stores semantic `pattern` and `raw_contract`; it does not store execution-model policy.

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

## Observability boundary

Unify observability contracts, not runtime mechanics:

```text
explicit Stream/Task or batch apply
  -> CONTROL.PIPELINE_RUN
  -> CONTROL.PIPELINE_EXECUTION_METRICS_V

Dynamic Table
  -> INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V

both
  -> CONTROL.DATASET_OBSERVABILITY_V
  -> health / SLA
```

Do not insert fake `PIPELINE_RUN` rows for Dynamic Tables. Do not create a second competing unified Silver observability abstraction unless a concrete contract cannot fit the existing path.

## Deployment / DDL / ownership guardrails

Framework generates once; domain owns forever. Existing dataset/version SQL is not rewritten by framework upgrades.

CONTROL and SILVER are checksum-locked apply-once migrations. Same applied path/checksum/order skips; changed/reordered/removed applied history or unresolved STARTED/FAILED blocks.

New persistent version-owned objects are create-only/fail-closed. Candidate deployment never changes stable consumer objects. Explicit release/rollback is the only generated stable-view replacement boundary and uses `COPY GRANTS`.

Do not introduce deployment-time scaffolding, hidden runtime metadata routing, a central SCD engine, arbitrary orchestration DSLs, or dbt as the Bronze-to-Silver engine.

## Immediate next implementation priority

Continue in this order unless real Snowflake evidence changes priorities:

```text
1. narrow Task operational configuration (Prompt 10)

   First version may support only:
     - minimum trigger interval
     - timeout
     - suspend after failures
     - warehouse override
     - optional error integration

   Do not add yet:
     - generic task-graph retry / TASK_AUTO_RETRY_ATTEMPTS abstraction
     - arbitrary schedules
     - universal readiness DSL
     - a general orchestration framework

2. configurable domain health evaluation interval (Prompt 11)

   Current released 040_health_task.sql contains the historical 1 MINUTE schedule.
   NEVER edit released 040.
   Introduce a new later migration/configuration mechanism instead.
   Policy should support domain-appropriate cadence rather than asserting one global best value.

3. Dynamic Table observability enrichment (Prompt 6)

   Migration 100 already provides the native evidence path and health consumes
   CONTROL.DATASET_OBSERVABILITY_V. Only enrich concrete missing native fields such as
   refresh action/trigger, target lag, statistics, state code/message or query id if useful.
   Do not create another unified execution-health view.
```

Task operational settings must remain **version-local execution policy**. Do not put them in the logical dataset/source manifest or conflate them with SLA.

## New conversation starter

```text
Continue enterprise-snowflake framework.
First read docs/NEXT_CHAT_HANDOFF.md, docs/CURRENT_CONTEXT.md,
docs/architecture/NAMING_AND_LAYERS.md and the architecture doc relevant to the task.
Then re-check current GitHub main, open PRs and CI before modifying code.
Continue from the immediate-next-work section; do not redesign completed apply-once,
metrics, release-readiness, provenance, DDL safety, certification or execution-model work.
```
