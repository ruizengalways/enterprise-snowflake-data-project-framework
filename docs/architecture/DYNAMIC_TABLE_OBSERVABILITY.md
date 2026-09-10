# Dynamic Table observability

## Purpose

Dynamic Tables execute through Snowflake's native refresh engine. The Framework therefore observes them through Snowflake-native metadata instead of fabricating `CONTROL.PIPELINE_RUN` rows that pretend a Dynamic Table is an explicit apply procedure.

The stable path is:

```text
INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
INFORMATION_SCHEMA.DYNAMIC_TABLES
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V
  -> CONTROL.DATASET_OBSERVABILITY_V
  -> domain health / SLA / incidents
```

Migration `100_dynamic_table_observability.sql` established this boundary and is immutable. Framework 0.25 adds `140_dynamic_table_observability_enrichment.sql` to enrich the same two views.

## Why a later migration

Released Control migrations are apply-once, checksum-locked history. Migration 100 must not be edited merely because Snowflake now exposes more useful native metadata.

Migration 140 therefore uses `CREATE OR REPLACE VIEW ... COPY GRANTS` for the two existing observability views. It creates no runtime table, task, procedure, scheduler or competing health abstraction.

## Native refresh evidence

`CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V` keeps detailed current/recent diagnostics from `DYNAMIC_TABLE_REFRESH_HISTORY`, including:

```text
refresh state / state code / state message
query id
data timestamp
refresh start / end
completion target
refresh action
refresh trigger
reinitialization reason
refresh target lag
raw STATISTICS
INPUTS_WITH_CHANGED_DATA
```

The view also exposes selected numeric values from the native `STATISTICS` object:

```text
inserted / deleted / copied rows
added / removed partitions
queued / compilation / execution milliseconds
```

These are Snowflake refresh-engine diagnostics. They are not mapped into the explicit-pipeline `ROWS_AFFECTED` metrics contract because they do not have the same semantics.

## Current scheduling and lag state

The same detail view joins the native `INFORMATION_SCHEMA.DYNAMIC_TABLES` function so an operator can see current scheduling state even when no new refresh-history row is available.

Useful fields include:

```text
current target lag and lag type
scheduling state
scheduling reason code / message
suspended / resumed timestamps
mean lag
maximum lag
time above target lag
time-within-target-lag ratio
latest data timestamp
last completed refresh state / code / message
currently executing refresh query id
```

A currently executing refresh takes precedence over the previous completed refresh when deriving normalized `SILVER_STATUS = RUNNING`.

## Unified operational surface

`CONTROL.DATASET_OBSERVABILITY_V` remains the one cross-execution-model operational surface. It exposes only a compact Dynamic Table subset useful for normal triage:

```text
scheduling state + reason
target / mean / maximum lag
time above target and within-target ratio
refresh action / trigger / reinitialization reason
queued / compilation / execution duration
refresh query id
```

Large/raw diagnostic payloads such as `STATISTICS` and `INPUTS_WITH_CHANGED_DATA` stay in `CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V` rather than bloating the common dataset view.

## Latency and freshness semantics

For Dynamic Tables, `LATEST_DATA_AT` comes from the refresh data timestamp, with the current Dynamic Table `LATEST_DATA_TIMESTAMP` as a native fallback when recent completed-history evidence is unavailable.

`BRONZE_TO_SILVER_LATENCY_SECONDS` is only calculated when an actual refresh end timestamp exists. A current data timestamp alone is not enough to invent a completed processing duration.

Dynamic Table target lag remains execution policy. It is not automatically converted into a logical dataset SLA threshold.

## Information Schema vs Account Usage

The core health path intentionally uses database-local Information Schema functions because operations need current/recent evidence and the domain already owns its database-local Control Plane.

Long-retention historical analytics can use Snowflake Account Usage separately when required. The Framework does not move normal health evaluation onto a higher-latency account-wide reporting surface merely to gain longer retention.

## Visibility and failure semantics

Snowflake metadata visibility depends on privileges such as object monitoring. Missing native visibility must remain observable as missing/unknown evidence; the Framework does not manufacture a successful refresh state.

The Framework also does not infer business correctness from refresh success. DQ and reconciliation remain separate evidence contracts.

## Deliberately absent

This design does not add:

- fake Dynamic Table `CONTROL.PIPELINE_RUN` rows;
- a second unified execution-health view;
- a Dynamic Table-specific runtime ledger maintained by Framework tasks;
- automatic SLA thresholds derived from target lag;
- Account Usage as the low-latency operational source;
- executable repair logic based on refresh metadata.

The goal is richer native evidence while preserving the existing runtime and health boundaries.
