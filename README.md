# Enterprise Snowflake Data Project Framework

Versioned golden path for Snowflake data-project repositories.

## Purpose

Implement reusable technical behaviour once so Health, Transport and future domains do not copy/paste or independently reimplement platform mechanics.

Shared mechanics belong here when a bug fix would otherwise require coordinated edits across every project repo. Business joins, calculations, source predicates and domain rules remain explicit project SQL/code.

## Current executable baseline

```text
src/enterprise_snowflake_framework/
├── workspaces.py
├── query_tags.py
├── metadata_validation.py
├── targets.py
├── dbt_context.py
└── dbt_vars.py

project_schema/
├── project.schema.json
├── dataset.schema.json
└── raw_contract.schema.json

scripts/
├── render_workspace_sql.py
├── render_query_tag.py
├── resolve_dbt_target.py
├── render_dbt_vars.py
├── render_dbt_context.py
└── assert_dbt_manifest.py

dbt_package/macros/
├── environment/targets.sql
├── loading/strategies.sql
└── capture/
    ├── primitives.sql
    └── dynamic_tables.sql

docs/patterns/capture-archetypes.md

.github/actions/
├── validate-metadata/action.yml
└── dbt-static-check/action.yml

.github/workflows/
├── framework-ci.yml
└── pr-workspace.yml
```

## Workspace + execution context

```text
personal DEV: <DEVELOPER>_<LAYER>
PR CI:        PR_<NUMBER>_<LAYER>
```

The target/context renderer derives database, warehouse, schema prefix and canonical run-level QUERY_TAG. Project model SQL uses `ref()` / `source()` rather than hard-coded DEV/UAT/PROD names.

Current stable reference:

```text
dbt-core      1.12.3
dbt-snowflake 1.12.0
```

Machine profiles use Snowflake workload identity + OIDC + short-lived tokens. No passwords/private keys belong in project profiles.

## Project and RAW capture contracts

Version 1 schemas cover project identity, dataset technical behavior and project-owned RAW contracts.

Dataset metadata includes:

```text
raw_contract
load_strategy
implementation
business_key
watermark_column
freshness
reconciliation
```

RAW contracts can classify source capture with a bounded block:

```yaml
capture:
  archetype: full_change
  fidelity: full_change
  checkpoint_kind: source_position
  ordering_columns: [source_sequence]
  idempotency_columns: [patient_id, source_sequence]
```

Supported archetypes:

```text
snapshot
watermark
net_change
full_change
snapshot_diff
cursor_or_file
```

Supported fidelity:

```text
current_state
net_change
full_change
full_event
```

Validator rules deliberately prevent overstating source fidelity. It validates archetype/fidelity/checkpoint compatibility, lookback usage, declared ordering/idempotency columns, non-null business keys and snapshot-diff delete semantics.

Metadata remains bounded technical metadata. It does **not** contain MERGE SQL, task graphs, arbitrary predicates or workflow branching.

See `docs/patterns/capture-archetypes.md` and platform ADR-031.

## Classic Snowflake first; Dynamic Tables optional

Every reusable pattern has a non-Dynamic-Table path using native Snowflake objects:

```text
TABLE
STREAM / CHANGES where useful
TASK / triggered TASK / task graph
MERGE / INSERT / DELETE
Snowflake Scripting
Time Travel / CLONE
```

Dynamic Tables are optional alternate engines for declarative projections after performance/operability proof. They are never the only implementation and are not the canonical SCD2 mechanism.

Authoritative RAW is replayable evidence when history, delete inference or recovery matters:

- full snapshots are retained as append snapshot batches before latest/diff projections;
- full CDC/events are appended to normal tables before current-state merges;
- Snowflake Streams are consumers/offsets, not full source-history storage;
- source cursor/watermark/file progress remains explicit runtime state.

## Executable capture SQL primitives

The dbt package now provides reusable classic primitives:

```text
esf_latest_observation
  -> deterministic latest row per business/idempotency key
  -> useful for watermark lookback, net CDC and SCD1 current projection

esf_snapshot_diff
  -> compares snapshot N vs N-1
  -> emits INSERT / UPDATE / DELETE using business key + record hash

esf_merge_current_state_sql
  -> Snowflake MERGE
  -> optional tombstone/delete branch
  -> UPDATE ALL BY NAME / INSERT ALL BY NAME for same-shape Bronze current projections
```

The project still owns the actual SELECT/source predicate and domain semantics.

Optional declarative projection wrapper:

```text
esf_dynamic_table_projection_sql
```

It requires an explicit production refresh mode:

```text
INCREMENTAL | FULL | ADAPTIVE
```

`AUTO` is intentionally not a framework production default. `CUSTOM_INCREMENTAL` is a separate DML contract and is not silently substituted for the classic implementation.

## Basic standard load strategies

A standard model identifies its governed dataset:

```jinja
{{ enterprise_snowflake_framework.esf_configure_dataset('vehicle_position') }}
```

The framework currently maps:

```text
full_refresh      -> table
append_only       -> incremental + append
incremental_merge -> incremental + merge + metadata business key
```

`append_only` does not invent a source/checkpoint predicate. The selected rows are the rows appended.

The basic macro deliberately rejects:

```text
implementation: custom
scd2_snapshot
scd2_merge
scd2_stream_task
```

Dedicated SCD2 implementations and invariant tests remain separate work.

## Runtime checkpoint boundary

Mutable capture progress does not live in Git metadata. The platform repository now owns the first real `PLATFORM_CONTROL.OPERATIONS` consumer:

```text
PIPELINE_CHECKPOINT
ADVANCE_PIPELINE_CHECKPOINT(...)
```

The same runtime contract can hold watermark, cursor, LSN/source position, event offset, snapshot ID or file identity. Advance it only after successful target processing; when atomicity is required, target DML and checkpoint advancement belong in the same explicit transaction/Snowflake Scripting unit.

## Query tags

Canonical compact JSON `QUERY_TAG` fields:

```text
required: project, environment, workload
optional: source, pipeline, dataset, run_id, git_sha, pr_number, operation
```

The dbt context carries a run-level tag and dataset vars can carry model-level tags. Do not put personal, secret, regulated or business-payload data in query tags.

## CI proof

Framework CI validates Python metadata/context utilities, pinned dbt installation, offline parse/compile, physical target resolution, basic load config and generated capture SQL. Capture smoke models cover tombstone MERGE, latest-observation dedupe, snapshot diff, and the explicit-mode Dynamic Table wrapper.

This is source/compile proof. Live Snowflake execution, concurrency, performance and recovery behavior still require real DEV infrastructure.

## Reusable PR workspace workflow

`.github/workflows/pr-workspace.yml` creates/drops guarded `PR_<n>_*` schemas through the domain CI service identity. It requests an account-scoped GitHub OIDC token and runs only framework-generated workspace SQL, not arbitrary PR business code with Snowflake credentials.

## Approved load-strategy vocabulary

```text
full_refresh
append_only
incremental_merge
scd2_snapshot
scd2_merge
scd2_stream_task
```

## Consumption model

Projects consume immutable framework revisions and upgrade deliberately. They do not copy shared implementation and do not follow framework `main` implicitly.

## Next framework growth

```text
checkpoint-aware watermark/lookback runner
append-only event Stream + triggered Task templates
reconciliation/freshness/audit primitives
dedicated SCD2 snapshot/merge/stream-task implementations + invariants
optional Dynamic Table equivalents for suitable SCD1/current projections
DEV/UAT/PROD delivery contracts
rollback/recovery/backfill templates
```

Do not add domain business logic here.

Canonical architecture/status are maintained in:

```text
enterprise-snowflake-platform-infra/docs/CURRENT_CONTEXT.md
enterprise-snowflake-platform-infra/docs/PROJECT_BLUEPRINT.md
```
