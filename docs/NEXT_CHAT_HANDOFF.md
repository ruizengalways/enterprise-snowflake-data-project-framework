# Next chat handoff

Read this file first when continuing the Framework in a new conversation. Then read `docs/CURRENT_CONTEXT.md`, `docs/architecture/RUN_EVIDENCE.md`, and the architecture document most relevant to the next task.

## Stable repository state

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.20.0
0.20 code merge = 8647190c175d4c6b815e46eb78574aea475a5040
merged PR  = #29 fix: make Silver pipeline metrics semantically consistent
PR CI      = Silver-first Toolkit CI #263 = SUCCESS
main CI    = Silver-first Toolkit CI #264 = SUCCESS
Snowflake certification workflow run #20 = SKIPPED
```

This handoff is committed after the 0.20 code merge, so always re-check the current `main` SHA before changing code. The certification skip is intentional while the trusted Snowflake certification environment is not explicitly enabled/configured. **No 0.20.0 SHA has yet produced a real `status = CERTIFIED` Snowflake artifact.** Static CI is not Snowflake certification.

## What 0.20 changed

0.20 fixes a real observability semantics problem. Older generated procedures could treat Snowflake `SQLROWCOUNT` after `MERGE` as if it meant update-only rows. It does not: it is the total row count affected by that DML statement. Older generated code also assigned `QUERY_ID = LAST_QUERY_ID()` only during later success logging, so the recorded ID could refer to a logging/transaction statement rather than the transformation DML.

New generated explicit Silver apply procedures use canonical metrics contract version 1:

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

The invariant is:

```text
ROWS_AFFECTED
  = SQLROWCOUNT for the primary Silver DML

DML_QUERY_ID
  = SQLID captured immediately after that same DML
```

`AFFECTED_BUSINESS_KEYS` is the number of distinct logical keys considered in the run. Pattern-specific physical work belongs in `METRICS`, not in misleading universal columns.

Pattern behavior:

```text
append
  canonical rows_affected = output INSERT rows
  metrics.output_rows_inserted

full_refresh
  canonical rows_affected = INSERT OVERWRITE rows written
  metrics.snapshot_rows_written

scd1
  canonical rows_affected = total MERGE rows affected
  metrics.merge_rows_affected
  do NOT label this ROWS_UPDATED

scd2
  canonical rows_affected = rebuilt history INSERT rows
  metrics.events_inserted
  metrics.history_rows_deleted
  metrics.history_rows_rebuilt
  each important DML also keeps its own captured query id
```

The old `ROWS_INSERTED`, `ROWS_UPDATED`, `ROWS_DELETED` columns remain for historical compatibility. They are not a cross-pattern contract. New code only fills them when the meaning is unambiguous; SCD1/SCD2 do not fabricate a breakdown.

## Control Plane through 0.20

Fresh domain control manifest includes:

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

Never edit already released 001..110 migration templates in place after release. Future fixes append a later migration.

Migration 110 adds to `CONTROL.PIPELINE_RUN`:

```text
METRICS_CONTRACT_VERSION
ROWS_AFFECTED
AFFECTED_BUSINESS_KEYS
DML_QUERY_ID
METRICS
```

and creates the stable read surface:

```text
CONTROL.PIPELINE_EXECUTION_METRICS_V
```

The view aliases existing timing evidence as `DATA_MAX_AT` / `PUBLISHED_AT` and exposes old row-count fields with `LEGACY_` names for audit.

Migration 110 does not rewrite existing generated apply procedures. Generated-once/domain-owned still means old implementations keep their historical SQL until a domain creates a new implementation version or manually migrates its owned code.

For an old domain, rerun `esf init-project` to materialize missing migration files, review `esf control-plan`, and explicitly append adopted migrations without reordering already-applied entries. `esf-control-preflight` now recognizes 110 as a Framework migration.

## Core model that remains stable

Logical dataset semantics and version implementation technology remain separate:

```text
logical dataset
  pattern = append | full_refresh | scd1 | scd2 | custom

implementation version
  execution_model = stream_task | dynamic_table | batch_sql | custom
```

The source manifest stores semantic `pattern` and `raw_contract`; it does not store `execution_model`.

Supported execution matrix remains deliberately fail-closed:

```text
append       + stream_task   = supported
full_refresh + stream_task   = supported
full_refresh + dynamic_table = supported
full_refresh + batch_sql     = supported
scd1         + stream_task   = supported
scd1         + dynamic_table = supported
scd2         + stream_task   = supported
custom       + custom        = supported / domain-owned

append       + dynamic_table = rejected
scd2         + dynamic_table = rejected
other unimplemented combinations = rejected
```

Do not add `procedure` as an execution model; it is an implementation artifact.

## Observability boundary

Unify observability contracts, not runtime mechanics:

```text
explicit Stream/Task or batch apply
  -> CONTROL.PIPELINE_RUN
  -> CONTROL.PIPELINE_EXECUTION_METRICS_V for canonical explicit-run metrics

Dynamic Table
  -> INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V

both
  -> CONTROL.DATASET_OBSERVABILITY_V
  -> health / SLA
```

Do not insert fake `PIPELINE_RUN` rows for Dynamic Tables and do not add a second competing unified Silver observability view unless there is a concrete missing contract that cannot fit the current surface.

## Deployment / DDL / release guardrails

CONTROL and SILVER are checksum-locked apply-once migrations. Same applied path/checksum skips; changed/reordered/removed applied history or unresolved STARTED/FAILED blocks.

New persistent version-owned objects are create-only/fail-closed. Candidate deployment never changes stable consumer objects. Explicit release/rollback is the only generated stable-view replacement boundary and uses `CREATE OR REPLACE VIEW ... COPY GRANTS`. Old runtime processing is retired last.

Do not introduce deployment-time scaffolding, hidden runtime metadata routing, a central SCD engine, or dbt as the Bronze-to-Silver engine.

## Dynamic Table remains first-class

Dynamic Table supports `scd1` and `full_refresh` in the current matrix. It does not generate fake Stream/Task/apply/replay artifacts. Native refresh history remains its execution evidence. Lifecycle, repair, release, rollback and certification are execution-model aware.

The trusted certification suite includes a cross-execution-model scenario:

```text
SCD1 v1 stream_task
  -> v2 dynamic_table
  -> native refresh / catch-up
  -> DQ + comparison
  -> COPY GRANTS cutover
  -> health
  -> rollback
```

A revision is only Snowflake-certified when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

## Immediate next implementation priority

Continue the roadmap in this order unless new live Snowflake evidence changes it:

```text
1. release preflight / postflight / RELEASE_RUN audit
   + strict single-active/single-candidate invariants
   (Prompt 8 + the invariant portion of Prompt 13)

2. template provenance + read-only upgrade-plan advisory
   (Prompt 7)

3. documentation vocabulary consistency guard
   (Prompt 12)

4. narrow Task operational configuration
   (Prompt 10)

5. configurable domain health evaluation interval via a NEW migration
   (Prompt 11; never edit released 040)

6. Dynamic Table observability enrichment only if evidence is still missing
   (Prompt 6; do not build a second abstraction)
```

For the next feature, prefer strong release preconditions and audit over a large candidate state machine. Retain `CONTROL.DATASET.CANDIDATE_VERSION` for now but enforce invariants such as:

```text
exactly/at most one ACTIVE version as appropriate
at most one candidate per logical dataset
candidate != active
CANDIDATE_VERSION references a non-retired version
registering another candidate while one exists fails closed
release from_version must equal ACTIVE_VERSION
```

Do not immediately replace the existing states with a speculative DEVELOPMENT/BOOTSTRAPPING/SHADOW/VALIDATED state machine unless real operations own every transition.

## New conversation starter

```text
Continue enterprise-snowflake framework.
First read docs/NEXT_CHAT_HANDOFF.md, docs/CURRENT_CONTEXT.md,
docs/architecture/RUN_EVIDENCE.md and docs/architecture/EXECUTION_MODELS.md.
Then re-check current GitHub main, open PRs and CI before modifying code.
Continue from the immediate-next-work section; do not redesign completed apply-once,
DDL safety, certification, execution-model separation or canonical metrics work.
```
