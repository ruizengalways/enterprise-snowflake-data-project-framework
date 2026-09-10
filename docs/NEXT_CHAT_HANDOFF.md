# Next chat handoff

Read this file first when continuing the Framework. Then read `docs/CURRENT_CONTEXT.md` and the architecture document most relevant to the next task.

## Current Framework release identity

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.26.0
```

Always re-check current `main`, open PRs and CI before changing code. Static CI is not Snowflake certification. A revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

## Stable architecture boundary

The Framework is a developer toolkit/bootstrapper, not a universal runtime interpreter. It generates explicit source code once; the domain commits, reviews and owns that code forever. Framework upgrades never silently rewrite domain-owned Silver implementations.

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

A domain owns writable `CONTROL`. Cross-domain observability is read-only aggregation. dbt starts from trusted Silver and owns downstream Gold/Mart/Semantic work; dbt is not the Bronze-to-Silver execution engine.

Logical pattern and execution model remain separate:

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

## 0.26 — input idempotency hardening

A real Transport-domain adoption exposed a generated-template correctness defect in Framework 0.25: target-side `NOT EXISTS` handled identities already persisted, but duplicate identities within one apply/replay input batch could both pass the target check.

Framework 0.26 hardens only the affected generated contracts:

```text
append_stream_task  revision 2 -> 3
scd2_stream_task    revision 2 -> 3
```

The behavior is now:

```text
same identity + conflicting payload -> fail closed with E_IDEMPOTENCY_CONFLICT
same identity + identical payload   -> collapse to one row/event in the batch
already persisted identity           -> existing target/event-ledger guard remains
```

Identity comparison is NULL-safe with `IS NOT DISTINCT FROM`; 0.26 does not invalidate existing RAW v2 contracts merely because an idempotency component is nullable. Conflicting payload detection uses a canonical JSON signature (`TO_JSON(ARRAY_CONSTRUCT_KEEP_NULL(...))`) instead of relying on a finite hash collision domain or selecting an arbitrary winner.

SCD2 event identity remains `RAW idempotency_key + ESF_STREAM_ACTION`. Delete/insert semantics are unchanged. Apply and replay use the same rule, and full replay checks conflicts before destructive candidate clearing. See `docs/architecture/INPUT_IDEMPOTENCY.md`.

`esf upgrade-plan` remains read-only. A 0.25 append/SCD2 rev2 implementation reports `UPDATE_AVAILABLE`; it is never rewritten in place. SCD1, full-refresh, Dynamic Table and custom revisions do not advance in 0.26.

## Earlier stable contracts

Framework 0.20 established canonical explicit-pipeline metrics: `ROWS_AFFECTED = SQLROWCOUNT` for the primary Silver DML and `DML_QUERY_ID = SQLID` captured immediately after that DML.

Framework 0.21 added guarded release readiness and release audit. `BLOCKED` has no bypass; `REVIEW_REQUIRED` requires explicit operator acceptance and reason.

Framework 0.22 added deterministic template provenance and read-only `esf upgrade-plan` statuses: `CURRENT`, `UPDATE_AVAILABLE`, `ADVISORY`, `UNKNOWN`, `UNVERIFIED`.

Framework 0.23 added narrow version-local Stream/Task operational policy: warehouse, minimum trigger interval, timeout, suspend-after-failures and optional error integration. Do not expose arbitrary schedules or generic task graphs.

Framework 0.24 added explicit audited health-evaluator cadence operations through `130_health_evaluation_cadence.sql` without editing released migration 040.

Framework 0.25 added `140_dynamic_table_observability_enrichment.sql`, enriching the existing Snowflake-native Dynamic Table evidence path without fabricating `PIPELINE_RUN` rows or creating a second unified observability layer.

## Current Control Plane migration chain

Framework 0.26 adds **no Control migration**. Fresh projects still contain:

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

Released numbered migrations are immutable. Never edit `001..140` in place after release; append a later migration only when a Control contract actually changes.

For an older domain, rerun `esf init-project` to materialize missing Framework files, then use `esf control-plan`. Existing `control_plane/deploy_manifest.txt` stays domain-owned and is never silently rewritten.

## Observability boundary

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

Unify evidence contracts, not runtime mechanics. Do not fabricate Dynamic Table `PIPELINE_RUN` rows or introduce a second unified execution-health abstraction.

## Ownership and deployment guardrails

Framework generates once; domain owns forever. CONTROL and SILVER are checksum-locked apply-once migrations. New persistent version-owned objects are create-only/fail-closed. Candidate deployment never changes stable consumer objects; explicit release/rollback is the stable-view replacement boundary.

Do not introduce deployment-time scaffolding, hidden metadata routing, one central SCD runtime, arbitrary orchestration DSLs or automatic production repair.

## Immediate next implementation priority

After 0.26 is merged and credential-free CI is green, return to `ruizengalways/enterprise-snowflake-transport-analytics`.

The existing unmerged Phase 2 shadow Silver v1 implementations were generated with Framework 0.25 and must not be adopted as-is. Regenerate them from the **exact merged Framework 0.26 SHA**, then verify:

```text
fleet_mssql.vehicle_status
  -> scd2_stream_task revision 3
  -> reviewed key/order/tracked/tombstone semantics unchanged
  -> batch conflict guard + NULL-safe event identity present

gtfs_realtime.vehicle_position
  -> append_stream_task revision 3
  -> reviewed idempotency identity unchanged
  -> batch conflict guard + NULL-safe target identity present
```

Keep these as shadow implementations first. Do not initialize/switch the current Control Plane or root Silver deployment manifest as a side effect of scaffolding. Compare legacy dbt Silver vs Framework v1 outputs and explicitly test duplicate-identity/conflicting-payload cases before any cutover decision.

The planned architecture roadmap through 0.25 is complete. Framework 0.26 is evidence-driven; future framework changes should likewise come from live Snowflake certification/integration evidence, a concrete domain adoption defect or a demonstrated operational gap.

## New conversation starter

```text
Continue enterprise-snowflake framework/domain adoption.
Read docs/NEXT_CHAT_HANDOFF.md and docs/CURRENT_CONTEXT.md.
Re-check current GitHub main, open PRs and CI before changing code.
Framework 0.26 is the evidence-driven idempotency hardening release.
If 0.26 is merged and green, return to transport analytics and regenerate the shadow Silver implementations from the exact merged 0.26 SHA before continuing Phase 2.
Do not silently rewrite domain-owned code or add speculative framework abstractions.
```
