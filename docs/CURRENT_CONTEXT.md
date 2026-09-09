# Current Context — Hybrid Framework v2

Updated: 2026-09-09

## Canonical state

Framework v2 is merged to `main`. The breaking v2 baseline merge is:

```text
7d3498f8b5ef48d868ea44aade62cf13e50e58f6
Framework v2 CI #193: SUCCESS
```

Framework PR #7 is the canonical redesign. Earlier stacked Framework PRs #3–#6 are closed as superseded and must not be used as architecture guidance or dependency pins.

## Architectural rule

```text
Metadata = HOW TO RUN
SQL      = WHAT THE DATA MEANS
```

Only schema v2 is supported for project, dataset and raw/source contracts. There is no v1 normalization layer, compatibility alias set, deprecated combination-strategy vocabulary or migration bridge.

## Ownership boundary

```text
Source -> Bronze = ingestion responsibility
Bronze -> Silver -> Gold = data processing responsibility
```

The Framework is connector-agnostic. SQL Server LSNs, Kafka offsets, API cursors and other connector-owned positions are not Framework checkpoints. `PLATFORM_CONTROL` processing checkpoints and bootstrap state describe already-landed Snowflake data only.

## Dataset execution model

Dataset policy is table/dataset scoped and uses three independent axes:

```text
load.strategy
materialization.type
runtime.mode
```

A single domain database can therefore contain full refresh, append-only, incremental merge, SCD1, SCD2, Dynamic Table and custom datasets together. Business joins, filters, CASE expressions, window logic, aggregation and KPI definitions remain ordinary domain SQL.

## Stateful correctness

Silver is the data-correctness layer.

SCD1 uses bounded keyed current-state maintenance with tombstone delete support. SCD2 uses one authoritative history materialization with deterministic ordering, replay safety, tombstone delete/reinsert semantics, `valid_from` / `valid_to` / `is_current` / `version_order`, a retained landed-event sidecar ledger, and late-arriving rebuild of affected business keys only.

Consumers use `<entity>_current` views; Gold should not duplicate `where is_current = true`.

## Gold and Snowflake-native execution

Gold is the business-derivation layer. Dynamic Tables are Gold-first and `ADAPTIVE` is preferred when a Dynamic Table is appropriate. Snowflake-native Streams, Tasks and platform history remain authoritative where Snowflake already owns the relevant runtime state.

## Control plane

Projects do not DML shared `PLATFORM_CONTROL` base tables. Runtime reads/writes go through domain-scoped views and guarded procedures. Config snapshots, run state, landed-data processing checkpoints, DQ/reconciliation, bootstrap handoff and reset/generation remain control-plane concerns.

## Current consumers

Transport and Health are merged to their `main` branches and both pin the immutable Framework v2 baseline SHA above for dbt packages and reusable workflows. Platform architecture is also merged and aligned with v2.

The standalone Transport and Health synthetic cores remain independent of Framework, `PLATFORM_CONTROL`, Terraform and enterprise WIF.

## Remaining acceptance gates

The repository design/static work is complete. The remaining proof is live infrastructure/runtime acceptance:

```text
configure DEV GitHub Environment + Snowflake WIF
-> prove account-scoped OIDC connection
-> deploy platform/control-plane objects
-> create/drop PR workspaces
-> run live SCD1/SCD2 scenarios
-> prove reset/generation rollover and guarded cross-domain access
-> run live Dynamic Table/deployment flows
```

Static CI must not be described as live Snowflake proof. Exact DEV -> UAT -> PROD same-SHA promotion orchestration should follow successful live DEV deployment proof rather than being guessed ahead of it.
