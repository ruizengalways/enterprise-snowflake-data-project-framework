# Reusable SCD Consumer Patterns

This framework treats SCD as a consumer of a declared capture contract. It never claims more history fidelity than the source provides, and it delegates CDC offsets, scheduling and run history to Snowflake when native primitives already own those concerns.

## Decision table

| Capture fidelity | SCD1 | SCD2 baseline | History guarantee |
| --- | --- | --- | --- |
| current state / watermark | latest-by-key current state | observed-version history only | only captured states |
| net change | deterministic current state | batch/observed history | intermediate source changes may already be lost |
| full change / full event | Dynamic Table or deterministic MERGE | Stream + Triggered Task + affected-key history rebuild | full captured change history |
| full snapshot | current projection | transactional snapshot close + insert | snapshot-granularity history |
| snapshot diff | current-state apply | consume derived diff or snapshot baseline | snapshot-granularity history |

## Snowflake-native split

For current-state/SCD1 transformations over an append-preserved source, prefer a Snowflake Dynamic Table when the SQL can be expressed declaratively. Snowflake owns change tracking, scheduling and refresh recovery. `esf_scd1_dynamic_table_sql()` is only a thin DDL wrapper around that native object.

For SCD2, use Streams + Tasks. Snowflake's current decision guide explicitly distinguishes SCD2 history from Dynamic Table current-state use cases. The framework therefore does **not** expose an SCD2 Dynamic Table wrapper.

Classic SCD1 MERGE remains available when a project needs procedural DML semantics that a normal Dynamic Table SELECT does not express cleanly.

## Strategy and capture compatibility

The metadata validator rejects structurally misleading combinations rather than letting a pipeline claim fidelity it cannot provide.

- `scd2_snapshot` requires a full `snapshot` capture contract.
- `scd2_stream_task` requires `full_change` or `full_event` fidelity and an append-preserved event capture archetype.
- `scd2_merge` is the correctness-first batch baseline for ordered captured changes. Its history guarantee still depends on source fidelity: watermark/net-change inputs can only preserve changes that were actually captured.

The implementation choice is downstream execution metadata; it does not redefine source fidelity.

## SCD target lifecycle

`esf_scd2_target_table_sql()` initializes a regular SCD2 history table from the payload/source table shape using `CREATE TABLE ... LIKE`, then adds:

```text
_ESF_VALID_FROM
_ESF_VALID_TO
_ESF_IS_CURRENT
_ESF_VERSION_ORDINAL
```

This DDL is a setup/deployment action and must not be placed inside the DML transaction that consumes a Stream. Schema evolution remains explicit and governed.

## SCD1 native baseline

For append-preserved CDC/event sources, the preferred current-state path is:

```text
immutable change/event table
        ↓
Dynamic Table
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY business key
    ORDER BY source ordering DESC
  ) = 1
        ↓
current state
```

`esf_scd1_dynamic_table_sql()` generates this pattern and defaults to `ADAPTIVE` refresh mode. This follows Snowflake's current recommendation for incrementalizable workloads while preserving an explicit override to `INCREMENTAL` or `FULL` when required.

## SCD1 classic fallback

`esf_scd1_merge_sql()` first collapses the incoming window to exactly one deterministic row per business key using source ordering, then performs current-state MERGE. Tombstones can delete current rows.

Use this when procedural MERGE semantics are genuinely required. A direct MERGE with multiple source rows matching the same target key can be nondeterministic, so the deterministic collapse remains mandatory.

## SCD2 snapshot baseline

`esf_scd2_snapshot_apply_sql()` is a correctness-first multi-DML transaction:

1. close current rows whose record hash changed;
2. close current rows missing from the new full snapshot (inferred delete);
3. insert new/current versions;
4. commit atomically.

Delete handling is end-dating by default rather than inventing a tombstone payload.

## SCD2 full-change baseline

`esf_scd2_event_history_select()` derives intervals from immutable, ordered source events. It removes consecutive no-op states by record hash, retains delete boundaries, and emits non-delete historical versions.

`esf_scd2_rebuild_affected_keys_sql()` rebuilds only keys touched by the current change set:

```text
immutable event history
        +
affected business keys
        ↓
recompute ordered state changes for those keys
        ↓
DELETE old target history for affected keys
        ↓
INSERT recomputed history
        ↓
COMMIT
```

This is the correctness-first full-change SCD2 algorithm because it is retry-safe and naturally repairs late/out-of-order events while immutable RAW history is retained.

`effective_at_column` must be part of `order_columns`. Additional source sequence/position columns make ordering deterministic. `_ESF_VERSION_ORDINAL` preserves ordering when multiple real changes share one timestamp.

## SCD2 Stream + Triggered Task baseline

For low-latency full-change/event workloads:

```text
immutable event table
        ↓
append-only Snowflake Stream
        ↓
Triggered Task (NO_OVERLAP)
        ↓
BEGIN TRANSACTION
  identify affected keys from Stream
  DELETE affected target history
  INSERT recomputed event history
COMMIT
```

Snowflake owns the Stream offset. The framework does not mirror that offset into `PLATFORM_CONTROL.PIPELINE_CHECKPOINT`.

Within one explicit Snowflake transaction, repeatable-read Stream semantics allow multiple statements to see the same change set. The Stream offset advances only when the transaction successfully commits; rollback preserves the offset.

The task itself is the Snowflake scheduler. Retry, timeout, failure suspension and overlap behavior use native Task properties. `TASK_HISTORY` / `COMPLETE_TASK_GRAPHS` are the authoritative run history; do not duplicate each Task run into `PIPELINE_RUN`.

Each independent consumer owns its own Stream.

## Snapshot diff is a fallback

If the source is already a mutable Snowflake table, use a standard Stream and native `METADATA$ACTION`, `METADATA$ISUPDATE` and `METADATA$ROW_ID` rather than maintaining two snapshots and diffing them yourself.

`snapshot_diff` remains only for external interfaces that genuinely expose complete snapshots without preserved source CDC.

## Executable invariants

The package exposes violation queries and dbt generic tests for structural invariants:

```text
esf_scd2_multiple_current_violations_sql()
esf_scd2_invalid_range_violations_sql()
esf_scd2_overlap_violations_sql()
esf_scd2_duplicate_version_violations_sql()
esf_scd2_invariant_summary_sql()

esf_scd2_one_current
esf_scd2_valid_ranges
esf_scd2_no_overlaps
esf_scd2_unique_version_ordinal
```

Every SCD2 implementation should additionally test deterministic behavioral fixtures:

- duplicate replay is idempotent;
- delete closes the active version;
- reinsert after delete opens a new version;
- late/out-of-order full-change event repairs history correctly;
- equal timestamps are resolved by deterministic source sequence/position;
- Stream advancement occurs only with successful target commit.

## What metadata does not contain

Metadata declares technical facts such as business key, capture fidelity, ordering identity and selected load strategy. It does not contain arbitrary MERGE SQL, task DAGs, business joins or executable branching. Those mechanics remain native Snowflake objects, framework code, or explicit project code depending on lifecycle ownership.
