# Next chat handoff

Read this file first when continuing the Framework. Then read `docs/CURRENT_CONTEXT.md` and the architecture document most relevant to the task.

## Current Framework release identity

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.27.0
```

Always re-check current `main`, open PRs and CI before changing code. Static CI is not Snowflake certification. A revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

## Stable architecture boundary

The Framework is a developer toolkit/bootstrapper, not a universal runtime interpreter. It generates explicit source code once; the domain commits, reviews and owns that code forever. Framework upgrades never silently rewrite domain-owned Silver implementations.

Logical layers remain Bronze, Silver, Gold/Marts, Semantic and cross-cutting Control. Default physical schemas remain `BRONZE`, `SILVER`, `GOLD_MARTS`, `SEMANTIC`, `CONTROL`. A domain owns writable `CONTROL`; cross-domain observability is read-only aggregation. dbt starts from trusted Silver and owns downstream Gold/Mart/Semantic work.

Logical pattern and execution model remain separate:

```text
pattern
  append | full_refresh | scd1 | scd2 | custom

execution_model
  stream_task | dynamic_table | batch_sql | custom
```

Supported combinations stay deliberately narrow; unsupported combinations fail closed. `procedure` is an implementation artifact, not an execution model.

## Evidence-driven fixes

### 0.26 — input idempotency

Transport adoption found that target-side `NOT EXISTS` did not deduplicate two same-identity rows inside one apply/replay batch. 0.26 therefore made append/SCD2 batches fail closed on same-identity conflicting payloads, collapse identical duplicates and use NULL-safe persisted identity joins.

```text
append_stream_task  -> revision 3
scd2_stream_task    -> revision 3
```

See `docs/architecture/INPUT_IDEMPOTENCY.md`.

### 0.27 — replay-stable SCD2 identity

Transport then exposed a narrower replay defect. A retained full-change tombstone row (`source_operation = D`) was being replayed as synthetic `ESF_STREAM_ACTION = DELETE`. That conflated reviewed source delete semantics with a Snowflake physical Stream action.

Framework 0.27 replays every retained Bronze evidence row as synthetic `ESF_STREAM_ACTION = INSERT`. Tombstone meaning remains in the reviewed RAW operation column/delete values, so SCD2 history still closes the prior state and emits no active tombstone row.

Only SCD2 advances:

```text
scd2_stream_task    revision 3 -> 4
append_stream_task  remains revision 3
```

`esf upgrade-plan` stays read-only. A 0.26 SCD2 rev3 version is `UPDATE_AVAILABLE`; a 0.26 append rev3 version remains `CURRENT` under 0.27.

## Earlier stable contracts

0.20: canonical explicit-pipeline `ROWS_AFFECTED` / `DML_QUERY_ID` metrics.

0.21: guarded release readiness and `CONTROL.RELEASE_RUN`; `BLOCKED` has no bypass.

0.22: deterministic template provenance and read-only upgrade planning.

0.23: narrow version-local Stream/Task operational settings; no arbitrary task-graph DSL.

0.24: explicit audited health-evaluator cadence operations via migration 130 without editing released migration 040.

0.25: Dynamic Table observability enrichment via migration 140, preserving the existing unified evidence surface and no fake `PIPELINE_RUN` rows.

## Current Control Plane migration chain

Framework 0.27 adds **no Control migration**. Fresh projects still contain:

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

Released numbered migrations are immutable. Existing domain deploy manifests remain domain-owned and are never silently rewritten.

## Immediate next implementation priority

After 0.27 is merged and credential-free CI is green, return to `ruizengalways/enterprise-snowflake-transport-analytics`.

Do **not** merge either old shadow branch generated from 0.25 or the temporary 0.26 SCD2 scaffold. Create/regenerate the current shadow implementations from the **exact merged 0.27 SHA**:

```text
fleet_mssql.vehicle_status
  -> scd2_stream_task revision 4
  -> business key vehicle_id
  -> ordering source_updated_at, source_sequence
  -> tracked status, depot_id, route_id
  -> source_operation D remains tombstone semantics
  -> replay stages retained tombstone rows with ESF_STREAM_ACTION = INSERT
  -> batch conflict guard + NULL-safe event identity remain

gtfs_realtime.vehicle_position
  -> append_stream_task revision 3
  -> idempotency vehicle_id, event_timestamp
  -> batch conflict guard + NULL-safe target identity remain
```

Keep them shadow-only: do not initialize/switch Control Plane state, do not create/adopt the root Silver deployment manifest, and do not cut production runtime as a scaffold side effect.

Then add explicit legacy-vs-shadow comparison evidence for duplicate identities, same-identity conflicting payloads, same timestamp/sequence, SCD2 consecutive identical state, late arrivals, tombstone delete/reinsert, and append duplicates. Any further Framework change must come from a concrete observed defect rather than roadmap momentum.

## New conversation starter

```text
Continue enterprise-snowflake framework/domain adoption.
Read docs/NEXT_CHAT_HANDOFF.md and docs/CURRENT_CONTEXT.md.
Re-check current GitHub main, open PRs and CI before changing code.
Framework 0.27 fixes replay-stable SCD2 tombstone event identity and only advances scd2_stream_task to revision 4.
If 0.27 is merged and green, regenerate Transport shadow Silver from the exact merged 0.27 SHA before continuing Phase 2.
Do not silently rewrite domain-owned code or add speculative framework abstractions.
```
