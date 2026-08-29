# Enterprise Snowflake Data Project Framework

Versioned golden path for Snowflake data-project repositories.

## Purpose

Implement reusable technical behaviour once so Health, Transport and future domains do not copy/paste or independently reimplement platform mechanics.

Shared mechanics belong here when a bug fix would otherwise require coordinated edits across project repos. Business joins, calculations, source predicates and domain rules remain explicit project SQL/code.

## Current capability baseline

Significant implementation areas:

```text
src/enterprise_snowflake_framework/
project_schema/
validation/
scripts/
dbt_package/macros/
dbt_package/tests/
examples/
tests/
docs/patterns/
.github/actions/
.github/workflows/
```

Reusable capabilities now include:

```text
workspace naming + guarded lifecycle SQL
canonical QUERY_TAG construction
dbt physical target/context resolution
project/dataset/RAW metadata validation
metadata -> dbt vars bridge
full_refresh / append_only / incremental_merge config
capture archetype helpers
checkpoint/runtime ledger helpers
freshness/reconciliation/check-result helpers
SCD1 merge
SCD2 snapshot
SCD2 immutable-event affected-key rebuild
SCD2 Stream + Triggered Task orchestration
SCD2 invariant tests + deterministic behavior oracle
optional Dynamic Table projection wrappers
reusable metadata/dbt static CI
reusable PR workspace workflow
reusable immutable project deployment workflow
```

The repository tree is the authority for individual implementation files; this README deliberately avoids maintaining an exhaustive file list.

## Workspace + execution context

```text
personal DEV: <DEVELOPER>_<LAYER>
PR CI:        PR_<NUMBER>_<LAYER>
```

The target/context renderer derives database, warehouse, schema prefix and canonical run-level QUERY_TAG. Project model SQL uses `ref()` / `source()` rather than hard-coded DEV/UAT/PROD names.

Current dbt baseline:

```text
dbt-core      1.12.3
dbt-snowflake 1.12.0
```

Machine profiles use Snowflake workload identity/OIDC with short-lived tokens. Passwords/private keys do not belong in project profiles.

## Project and RAW capture contracts

Version 1 schemas cover project identity, dataset technical behaviour and project-owned RAW contracts.

Dataset metadata includes bounded technical fields such as:

```text
raw_contract
load_strategy
implementation
business_key
watermark_column
freshness
reconciliation
```

RAW contracts classify source capture independently from downstream target strategy.

Supported capture archetypes:

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

Metadata validation checks archetype/fidelity/checkpoint compatibility, deterministic ordering/idempotency fields, key nullability, freshness/reconciliation structure and SCD/capture compatibility.

Metadata remains bounded technical metadata. It does **not** contain MERGE SQL, task graphs, arbitrary predicates, business formulas or workflow branching.

See `docs/patterns/capture-archetypes.md`, `docs/patterns/source-capture-matrix.md` and platform ADR-031.

## Snowflake-native first; Dynamic Tables optional

Classic/native primitives are the reliability baseline:

```text
TABLE
STREAM / CHANGES
TASK / Triggered Task / task graph
MERGE / INSERT / DELETE
Snowflake Scripting
Time Travel / CLONE
```

Dynamic Tables are optional declarative execution/projection choices. They are not the canonical SCD2 implementation and never become the only supported path.

Production Dynamic Table refresh mode is explicit; the framework does not default to `AUTO`.

Authoritative RAW remains replayable evidence when history/delete inference/recovery matters:

- full snapshots are retained as append snapshot batches before latest/diff projections;
- full CDC/events are appended to regular tables before Stream consumers/current-state merges;
- Streams own processing offsets but are not complete source-history storage;
- source cursor/watermark/file progress remains explicit runtime control state.

See `docs/patterns/snowflake-native-first.md`.

## Runtime state and quality boundary

Mutable runtime progress does not live in Git metadata.

Platform-owned operational state includes:

```text
PLATFORM_CONTROL.OPERATIONS.PIPELINE_CHECKPOINT
PLATFORM_CONTROL.OPERATIONS.PIPELINE_RUN
PLATFORM_CONTROL.OPERATIONS.PIPELINE_CHECK_RESULT
PLATFORM_CONTROL.OPERATIONS.ADVANCE_PIPELINE_CHECKPOINT(...)
```

Framework macros render the corresponding read/start/finish/check/reconciliation calls. Custom state is limited to information Snowflake does not already own; Stream offsets are not duplicated into a parallel custom offset ledger.

## SCD consumers

SCD is downstream of capture fidelity.

Implemented reusable paths:

```text
SCD1
  esf_scd1_merge_sql()

SCD2 snapshot
  esf_scd2_snapshot_apply_sql()

SCD2 full change/event
  esf_scd2_event_history_select()
  esf_scd2_rebuild_affected_keys_sql()

SCD2 Stream + Triggered Task
  esf_scd2_stream_task_sql()
```

The correctness-first event path rebuilds only affected business keys from immutable ordered event history, allowing duplicate replay and late/out-of-order events to repair target history.

Reusable SCD2 invariants cover:

```text
at most one current row per key
valid version ranges
no overlapping ranges
unique deterministic version ordinal
```

A deterministic SQL behavior oracle covers duplicate replay, no-op state, updates, delete/reinsert gaps, late events and ordering ties. Framework CI proves parse/render/discovery; live Snowflake execution remains a DEV gate.

See `docs/patterns/scd-consumers.md` and platform ADR-035.

## Reusable PR workspace workflow

`.github/workflows/pr-workspace.yml` creates/drops guarded `PR_<n>_*` schemas through the domain CI service identity.

Security properties:

- full immutable framework reference required;
- account-scoped Snowflake OIDC audience;
- project-specific `SU_GITHUB_<DOMAIN>_CI -> AR_<DOMAIN>_CI` identity;
- executes framework-generated workspace SQL only;
- does not run untrusted PR business code while holding Snowflake credentials.

## Reusable stable deployment workflow

`.github/workflows/project-deploy.yml` is the stable DEV/UAT/PROD delivery contract.

It requires:

```text
full 40-character project Git SHA
full 40-character framework Git SHA
```

The workflow verifies the project SHA belongs to `main` history, checks out the exact detached revision, verifies the project's dbt package pin matches the framework SHA, enters the selected protected GitHub Environment, requests an account-scoped OIDC token and runs dbt as:

```text
SU_GITHUB_<DOMAIN>_DEPLOY -> AR_<DOMAIN>_DEPLOY
```

Promotion changes environment, not source revision:

```text
same project SHA
DEV -> UAT -> PROD
```

## Approved load-strategy vocabulary

```text
full_refresh
append_only
incremental_merge
scd2_snapshot
scd2_merge
scd2_stream_task
```

`esf_configure_dataset()` handles the basic dbt-native strategies. Dedicated SCD macros own SCD behavior; the basic materialization helper does not pretend SCD2 is generic incremental MERGE.

## CI proof

Framework CI validates Python utilities, metadata contracts, target resolution, pinned dbt installation, offline parsing, generated Snowflake-native SQL, SCD invariant/test discovery, deterministic SCD2 oracle rendering and reusable-workflow security contracts.

This is source/static proof. Live Snowflake WIF, authorization, runtime execution, concurrency, performance and recovery still require real DEV infrastructure.

## Consumption model

Projects consume immutable framework revisions and upgrade deliberately. They do not copy shared implementation and do not follow framework `main` implicitly.

The current exact release SHA and verified cross-repository runs are recorded in:

```text
enterprise-snowflake-platform-infra/docs/CURRENT_CONTEXT.md
```

## Next framework growth

Do not add another abstraction merely because it is possible. Near-term growth should follow live DEV findings and real consumers, particularly:

```text
live runtime verification fixes
rollback/recovery/backfill workflow templates
operational evidence and promotion controls
later ingestion adapter support after platform proof
```

Do not add domain business logic here.
