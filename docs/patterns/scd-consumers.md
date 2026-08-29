# Reusable SCD Consumer Patterns

This framework treats SCD as a consumer of a declared capture contract. It never claims more history fidelity than the source provides.

## Decision table

| Capture fidelity | SCD1 | SCD2 baseline | History guarantee |
| --- | --- | --- | --- |
| current state / watermark | latest-by-key + MERGE | observed-version history only | only captured states |
| net change | deterministic per-key MERGE | batch/observed history | intermediate source changes may already be lost |
| full change / full event | deterministic per-key MERGE | affected-key event-history rebuild | full captured change history |
| full snapshot | current projection | transactional snapshot close + insert | snapshot-granularity history |
| snapshot diff | MERGE derived I/U/D | consume derived diff or snapshot baseline | snapshot-granularity history |

## SCD1 classic baseline

`esf_scd1_merge_sql()` first collapses the incoming window to exactly one deterministic row per business key using source ordering, then performs the current-state MERGE. Tombstones can delete current rows.

This is intentional: a direct MERGE with multiple source rows matching the same target key can be nondeterministic in Snowflake.

## SCD2 snapshot baseline

`esf_scd2_snapshot_apply_sql()` is a correctness-first multi-DML transaction:

1. close current rows whose record hash changed;
2. close current rows missing from the new full snapshot (inferred delete);
3. insert new/current versions;
4. commit atomically.

Target history carries framework columns:

```text
_ESF_VALID_FROM
_ESF_VALID_TO
_ESF_IS_CURRENT
_ESF_VERSION_ORDINAL
```

The target should be initialized from the same source payload shape plus these columns. Delete handling is end-dating by default rather than inventing a tombstone payload.

## SCD2 full-change baseline

`esf_scd2_event_history_select()` derives intervals from immutable, ordered source events. It removes consecutive no-op states by record hash, retains delete boundaries, and emits non-delete historical versions.

`esf_scd2_rebuild_affected_keys_sql()` then rebuilds only keys touched by the current batch:

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

This is deliberately the default full-change SCD2 algorithm because it is retry-safe and naturally repairs late/out-of-order events as long as the immutable RAW event history is retained. It trades some recomputation for correctness. Very high-volume workloads may add a project-specific optimized fast path after proving identical invariants.

`effective_at_column` must be part of `order_columns`. Additional source position/sequence columns should be included to make ordering deterministic. If multiple real changes share the same timestamp, `_ESF_VERSION_ORDINAL` preserves their sequence even when timestamp validity boundaries are equal.

## SCD2 Stream + Triggered Task baseline

For low-latency full-change/event workloads:

```text
immutable event table
        ↓
append-only Stream
        ↓
Triggered Task (NO_OVERLAP)
        ↓
BEGIN TRANSACTION
  INSERT OVERWRITE affected keys FROM stream
  DELETE affected target history
  INSERT recomputed event history
COMMIT
```

`esf_scd2_stream_task_sql()` generates this pattern. Stream consumption and history replacement happen in the same transaction. If the task fails before commit, the DML transaction rolls back and the stream offset is not successfully advanced.

Each consumer must own its own stream. Do not share one stream between independent consumers.

## Optional Dynamic Table versions

Dynamic Tables are optional projections, never a platform requirement:

```text
esf_scd1_dynamic_table_sql()
esf_scd2_dynamic_table_sql()
```

The caller must explicitly choose the Dynamic Table refresh mode. `AUTO` is not a framework production default.

The equivalent classic implementation must always remain deployable. Window-heavy SCD2 definitions can be valid for incremental Dynamic Table refresh while still being expensive because changes can cause the affected business-key partitions to be recomputed. Benchmark the standalone SELECT and Dynamic Table refresh history before production adoption.

## Required invariants

Every SCD2 implementation should test at least:

- at most one current row per business key;
- no overlapping validity ranges per business key;
- valid-to is not earlier than valid-from;
- deterministic ordering for equal timestamps;
- duplicate replay is idempotent;
- delete closes the active version;
- reinsert after delete opens a new version;
- late/out-of-order full-change event repairs history correctly;
- checkpoint/stream advancement occurs only with successful target commit.

## What metadata does not contain

Metadata declares technical facts such as business key, capture fidelity, ordering identity and selected load strategy. It does not contain arbitrary MERGE SQL, task DAGs, business joins or executable branching. Those mechanics remain framework code or explicit project code.
