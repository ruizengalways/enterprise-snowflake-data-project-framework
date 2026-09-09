# Snowflake-native processing first

The Framework starts after Bronze data exists and prefers Snowflake-native primitives for downstream reliability.

Preferred order:

```text
Snowflake native primitive
  -> thin Framework convention/helper when consistency matters
  -> explicit domain SQL when semantics differ
  -> custom runtime state only when genuinely necessary
```

## Stateful Silver

Use regular tables and explicit transactional DML for state/history correctness when procedural state matters. The standard SCD2 materialization keeps retained landed events in a technical sidecar table and rebuilds only affected keys.

Snowflake Streams/Tasks may be used for a project that explicitly chooses those runtime capabilities, but Stream offsets remain Snowflake-owned and are never copied into Framework checkpoint state.

## Dynamic Tables

Use Dynamic Tables for declarative SELECT-defined results where they fit operationally, especially Gold derivations. They are not the default mechanism for complex SCD2 state maintenance.

## Processing checkpoint state

`PLATFORM_CONTROL.OPERATIONS.PIPELINE_CHECKPOINT` may track progress over already-landed Snowflake evidence. It does not replace an ingestion connector checkpoint store.

## Task observability

When Snowflake Tasks are the runtime, Snowflake task history is authoritative for task execution. Framework observability may link dataset/config/Git context but should not build a second scheduler or duplicate Snowflake-owned offsets.

## Data quality

Prefer Snowflake-native quality capabilities when they directly represent the check. Keep explicit SQL for reconciliation and domain-specific checks. Framework DQ helpers stay bounded and technical.
