# Current Context — Hybrid Framework v2

## Architectural rule

```text
Metadata = HOW TO RUN
SQL      = WHAT THE DATA MEANS
```

Framework v2 is intentionally breaking. Only schema v2 is supported for project, dataset and raw/source contracts. There is no v1 normalization layer, compatibility alias set, deprecated public strategy vocabulary or migration bridge.

## Ownership boundary

```text
Source -> Bronze = ingestion responsibility
Bronze -> Silver -> Gold = data processing responsibility
```

The Framework is connector-agnostic. SQL Server LSNs, Kafka offsets, API cursors and other connector-owned positions are not Framework checkpoints. `PLATFORM_CONTROL` processing checkpoints describe already-landed Snowflake data only.

## Stateful correctness

Silver is the data correctness layer. SCD1 uses a bounded current-state materialization with tombstone delete support. SCD2 uses one authoritative history materialization with:

```text
deterministic ordering
idempotent replay
tombstone delete/reinsert semantics
valid_from / valid_to / is_current / version_order
retained landed-event sidecar ledger
late-arriving rebuild of affected business keys only
```

Consumers use `<entity>_current` views; Gold should not duplicate `where is_current = true`.

## Gold

Gold is the business derivation layer. Joins, KPI logic, aggregation and semantic preparation remain readable domain SQL. Dynamic Tables are Gold-first and `ADAPTIVE` is the default refresh mode when a Dynamic Table is appropriate.

## Control plane

Projects do not DML shared `PLATFORM_CONTROL` base tables. Runtime reads/writes go through domain-scoped views and guarded procedures. Config snapshots, run state, landed-data processing checkpoints, DQ/reconciliation, bootstrap handoff and reset/generation remain control-plane concerns.

## Portability

Transport and Health standalone synthetic cores remain independent of Framework, `PLATFORM_CONTROL`, Terraform and enterprise WIF. The enterprise adapter must never become a prerequisite for the portable domain demo core.

## Current integration branches

```text
Framework  feature/clean-hybrid-framework-v2
Transport  feature/hybrid-framework-v2
Health     feature/hybrid-framework-v2
Platform   feature/hybrid-framework-v2
```

The domain branches pin one immutable Framework v2 SHA. Live Snowflake acceptance remains outstanding until DEV/WIF actually runs successfully; static CI must not be described as live Snowflake proof.
