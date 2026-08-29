# Enterprise Source Capture Matrix

This is the operator-facing map from common source shapes to the smaller reusable framework archetypes in `capture-archetypes.md`.

The canonical authoritative evidence layer is the project-owned **RAW contract**. This document does not introduce a separate Bronze/Silver physical-layer vocabulary.

| # | Common source/capture | Framework capture | Source fidelity | Authoritative RAW evidence | Delete | Retry/lookback/idempotency | Classic Snowflake path | SCD1 | SCD2 guarantee | Optional Dynamic Table path |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | Full Snapshot | `snapshot` | `current_state` | append complete snapshot batches with `snapshot_id`, `snapshot_at`, `batch_id`, record hash | inferred by N vs N-1 | `snapshot_id + business_key` | append snapshot -> snapshot diff/current projection -> Task/dbt/MERGE | yes | snapshot-grain only | latest snapshot/current projection or declarative diff; snapshots remain normal tables |
| 2 | Incremental Watermark | `watermark` | `current_state` | append observed versions when replay matters; optional current projection | normally no | persisted watermark; dedupe `business_key + source timestamp/version` | read checkpoint -> source extract -> latest-by-key -> MERGE -> advance checkpoint | yes | observed changes only | latest-row/current projection after landed evidence |
| 3 | Watermark + Lookback | `watermark` | `current_state` | same as #2, allowing overlap | normally no | start at `last_successful_watermark - lookback`; deterministic overlap dedupe | overlap extract -> latest-by-key -> MERGE -> advance high watermark only after success | yes | observed changes only | same as #2 |
| 4 | Watermark + Soft-Delete Row | `watermark` | `current_state` | append/current observations containing retained delete state | soft-delete/tombstone **row** in current-state source | source version + business key; lookback optional | extract current rows -> dedupe/latest -> MERGE or mark delete -> checkpoint | yes | observed current-state versions only | current projection possible when delete semantics remain declarative |
| 5 | Native CDC — Net Changes -> MERGE | `net_change` | `net_change` | append each capture window before current MERGE | explicit delete/tombstone **change event** | CDC position + business key | append batch -> dedupe -> MERGE current | yes | net/batch history only | current-state declarative projection when appropriate |
| 6 | Native CDC — Net Changes -> APPEND | `net_change` | `net_change` | append one observed final change per key/window | explicit delete event | batch/source position + business key | append net-change evidence -> derive current with latest-by-key | yes | net/batch history, not full transaction history | latest-by-key current projection when refresh economics are good |
| 7 | Native CDC — All/Full Changes | `full_change` | `full_change` | immutable ordered change events | explicit/source-defined delete event | LSN/sequence/event identity | append events -> append-only Stream -> triggered Task -> SCD1 MERGE / SCD2 processor | yes | full if source ordering/completeness reliable | current/SCD1 projection only; SCD2 stays classic |
| 8 | Transaction Log CDC | `full_change` | `full_change` | immutable transaction-log events | explicit/source-defined delete event | LSN/SCN/log position | same as #7 | yes | full if log ordering reliable | same as #7 |
| 9 | Debezium / Kafka CDC | `full_change` | `full_change` | immutable CDC envelope/events | explicit/source-defined | topic + partition + offset; source LSN where available | Snowpipe Streaming/Kafka landing later -> normal event table -> append-only Stream/Task | yes | full if ordered and complete | current/SCD1 projection after landed events |
| 10 | Delta Change Data Feed | `full_change` | `full_change` | append Delta commit changes | source-defined | commit version + row identity/change type | ingest CDF -> append event table -> Stream/Task or dbt consumers | yes | full at CDF fidelity | current/SCD1 projection after landed CDF |
| 11 | Event Source | `full_change` | `full_event` | immutable business events | event-defined | event id / ordered source offset | append events -> Stream/triggered Task for derived state | yes when entity state is derivable | full event history; entity SCD2 depends on event semantics | declarative event-derived projections when suitable |
| 12 | Snapshot Diff | `snapshot_diff` | `net_change` | append snapshots **and** derived I/U/D diff | inferred | `snapshot_id + business_key` | retain N/N-1 -> `esf_snapshot_diff` -> append diff -> MERGE/SCD2 | yes | snapshot-grain | declarative diff/current projection; retained snapshots are classic fallback |
| 13 | API Cursor / Pagination Incremental | `cursor_or_file` | API-dependent | append response/change evidence before cursor advancement | API-defined | cursor + business/event key | read cursor -> call API -> land evidence -> transform/MERGE -> advance cursor | yes | API-dependent | downstream projection only; cursor state stays explicit |
| 14 | File Incremental | `cursor_or_file` | file-content-dependent | landed rows plus file metadata/identity | source/file-dependent | file path + content key/checksum + row identity | Stage + Snowpipe/COPY -> RAW table -> dedupe/reconcile -> MERGE/append | yes | file-content-dependent | downstream projection only; file ingestion ledger stays explicit |

## Mandatory interpretation rules

### Full snapshot

`OVERWRITE` may exist as a convenience/current projection. It must not be the only retained RAW object when delete inference, historical SCD2, replay, audit or reconciliation is required.

### Watermark

The high watermark is mutable runtime state. It advances only after target processing succeeds. Lookback deliberately rereads overlap and therefore requires deterministic deduplication.

A current-state soft-delete row remains a **watermark/current-state** pattern when it is delivered through the same source row/version interface. For example:

```text
id=300, updated_at=..., is_deleted=true
```

Do not reclassify that row as `net_change` merely because a source/vendor calls it a tombstone.

### Net CDC

Do not label net-change CDC as full history. If five source changes collapse into one final row before the extractor receives them, no downstream Snowflake implementation can reconstruct those four lost transitions.

A delete/tombstone **event** from a change feed belongs here or under `full_change`, depending on whether the feed exposes only one final result per entity/window or every captured change.

### Full CDC/event

Land immutable events before reducing them to current state. A Snowflake Stream is an offset-based change consumer over a Snowflake source object; it is not the authoritative source audit log.

`full_change` does not by itself guarantee before+after images. A reusable current/SCD consumer must only assume the state that the RAW source contract actually provides. Partial-update/delta-image reconstruction remains source-specific until an explicit reusable contract is justified.

### Files

Use Snowflake file metadata such as filename, row number and file content key where appropriate. Snowpipe duplicate-file tracking is useful ingestion protection, but the framework does not treat it as a permanent enterprise idempotency ledger.

## Standard execution-engine policy

```text
engine = classic     # mandatory implementation and break-glass path
engine = dynamic     # optional for supported declarative current/projection logic
```

Execution engine is an implementation/deployment choice, not a business contract. Switching between classic and Dynamic Table must not change RAW semantics or the published downstream contract.

### Classic baseline

```text
TABLE
STREAM / CHANGES
TASK / triggered TASK / task graph
MERGE / INSERT / DELETE
Snowflake Scripting
Time Travel / CLONE
PLATFORM_CONTROL checkpoint state
```

### Dynamic Table option

Use an explicit refresh mode in production. The framework wrapper currently allows:

```text
ADAPTIVE
INCREMENTAL
FULL
```

It intentionally does not silently default to `AUTO`. Dynamic Tables are not the framework's SCD2 implementation.

## Current v1 contract limitations

The current RAW schema intentionally remains small, but this means some production cases are not first-class yet:

```text
soft-delete row column/value semantics are not explicit metadata
before/after/delta image capability is not explicit metadata
truly keyless sources are not supported because business_key is required
safe initial snapshot -> incremental/CDC handoff is not a reusable framework contract yet
```

Do not hide these limitations by inventing a business key or pretending a current-state tombstone row is a change-feed event.

## Minimum onboarding questions

A new dataset should be classifiable from a small technical interview:

1. Is the source payload current state, net change, full change, or a business event?
2. Can the source represent delete? Is it a retained current-state delete row or a change-feed delete event?
3. What is the reliable non-null business/entity identity? If there is none, stop: v1 does not yet support a keyless contract and must not invent one.
4. What is the reliable source ordering/version/position, if any?
5. What identity makes retries idempotent?
6. What checkpoint does the source require: watermark, cursor, LSN/offset, snapshot ID or file identity?
7. Does the source permit overlap/lookback?
8. What history can the source actually guarantee?
9. For full-change feeds, does each event carry a reconstructible post-change state, before+after images, or only a delta?
10. What initial-load/position handoff prevents gaps and uncontrolled double-apply?

Those answers populate the bounded RAW `capture` contract where reusable fields exist. They do not generate business SQL or source-specific extraction logic.

For cross-repository implementation coverage against the wider pipeline-design catalogue, see `enterprise-snowflake-platform-infra/docs/architecture/PIPELINE_PATTERN_COVERAGE.md`.
