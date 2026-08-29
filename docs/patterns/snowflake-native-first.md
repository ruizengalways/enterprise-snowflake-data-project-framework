# Snowflake-Native First

The framework standardizes how projects use Snowflake. It does not reimplement Snowflake runtime services.

## Decision rule

Before adding framework state or a custom stored procedure/function, check whether Snowflake already owns the required state and execution semantics.

Preferred order:

```text
Snowflake GA/native primitive
  -> thin framework SQL/dbt wrapper when consistency helps
  -> explicit project SQL when semantics differ
  -> custom platform runtime state only when Snowflake has no equivalent
```

Preview features are not the default production baseline unless a project explicitly accepts the preview lifecycle.

## CDC inside Snowflake

### Mutable Snowflake table

Use a standard Stream:

```text
source table
  -> standard STREAM
     -> METADATA$ACTION / METADATA$ISUPDATE / METADATA$ROW_ID
        -> DML consumer
```

Use `esf_standard_stream_sql()` only as a thin DDL wrapper. The CDC offset belongs to Snowflake.

Do not create a framework checkpoint for this consumer.

### Immutable event / landing table

Use an append-only Stream:

```text
immutable event table
  -> APPEND_ONLY STREAM
     -> triggered task
```

Append-only streams are preferred when only inserted rows matter.

### Full snapshots from an external source

`snapshot_diff` remains a fallback only when the upstream interface genuinely provides snapshots and no source/Snowflake CDC primitive can preserve the changes.

## Stream lifecycle

Routine deployment uses `CREATE STREAM IF NOT EXISTS`.

A Stream's offset is runtime state. Do not routinely drop/recreate or replace a Stream to reconcile configuration. Changing its source object or append-only semantics is an explicit migration with a documented offset/replay decision.

Each independent consumer owns its own Stream.

## Triggered execution

Use Snowflake Triggered Tasks with `SYSTEM$STREAM_HAS_DATA` rather than polling a Stream from an external scheduler.

Use native task controls for:

- retry attempts;
- suspend-after-failure behavior;
- overlap policy;
- timeout;
- task success/error integrations where configured.

The framework should not build a second scheduler around a Snowflake Task.

## Task observability

For Snowflake Task-driven pipelines, Snowflake is the authoritative run ledger:

```text
INFORMATION_SCHEMA.TASK_HISTORY
INFORMATION_SCHEMA.COMPLETE_TASK_GRAPHS
ACCOUNT_USAGE task history/views for longer retention
```

Do not duplicate every Task run into `PLATFORM_CONTROL.OPERATIONS.PIPELINE_RUN`.

`PIPELINE_RUN` remains for executions whose authoritative orchestrator is outside Snowflake, for example a GitHub/dbt deployment or an external source extraction process.

## Checkpoints

Use `PLATFORM_CONTROL.OPERATIONS.PIPELINE_CHECKPOINT` only where the source system requires an application-owned cursor/watermark/source position.

Examples:

```text
REST API cursor
SQL Server LSN / source position
external file identity
external event offset not already owned by the ingestion service
```

Do not use it to mirror a Snowflake Stream offset.

## Data quality

On Enterprise Edition, prefer Snowflake Data Quality Monitoring for standard metrics:

```text
SNOWFLAKE.CORE.FRESHNESS
SNOWFLAKE.CORE.ROW_COUNT
SNOWFLAKE.CORE.UNIQUE_COUNT
SNOWFLAKE.CORE.MIN / MAX
expectations
SNOWFLAKE.LOCAL.DATA_QUALITY_MONITORING_EXPECTATION_STATUS
```

The framework can generate association/schedule SQL, but Snowflake performs the metric execution, stores the result and evaluates expectations.

Keep explicit SQL for checks Snowflake does not provide directly, especially cross-system or cross-table reconciliation bundles.

`esf_freshness_check_sql()` remains only as a fallback for cases the native FRESHNESS DMF cannot represent, such as source timestamp semantics/types that are intentionally incompatible with the system DMF association.

## SCD

Snowflake currently provides the execution/CDC primitives, not a single native `CREATE SCD2` object.

Therefore:

- use Streams for change offsets;
- use Triggered Tasks for change-driven execution;
- use Snowflake transactions for atomic target updates;
- use Task History for task run state;
- keep only the necessary SCD interval/history SQL in the framework.

Do not add a custom scheduler, custom Stream-offset table, or custom task-run ledger around this path.
