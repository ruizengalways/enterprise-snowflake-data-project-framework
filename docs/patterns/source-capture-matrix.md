# Enterprise Source Capture Matrix

This is the operator-facing map from common source shapes to the smaller reusable framework archetypes in `capture-archetypes.md`.

In this framework, "Bronze" means the project-owned authoritative RAW evidence layer. A physical schema named `BRONZE` is not required.

| # | Common source/capture | Framework capture | Source fidelity | Authoritative RAW evidence | Delete | Retry/lookback/idempotency | Classic Snowflake path | Silver SCD1 | Silver SCD2 | Optional Dynamic Table path |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | Full Snapshot | `snapshot` | `current_state` | append complete snapshot batches with `snapshot_id`, `snapshot_at`, `batch_id`, record hash | inferred by N vs N-1 | `snapshot_id + business_key` | append snapshot -> snapshot diff/current table -> Task/dbt/MERGE | yes | snapshot-grain only | latest snapshot/current projection or declarative diff; snapshots remain normal tables |
| 2 | Incremental Watermark | `watermark` | `current_state` | append observed versions when replay matters; optional current projection | normally no | persisted watermark; dedupe `business_key + source timestamp/version` | read checkpoint -> source extract -> latest-by-key -> MERGE -> advance checkpoint | yes | observed changes only | latest-row/current projection after landed evidence |
| 3 | Watermark + Lookback | `watermark` | `current_state` | same as #2, allowing overlap | normally no | start at `last_successful_watermark - lookback`; deterministic overlap dedupe | overlap extract -> latest-by-key -> MERGE -> advance high watermark only after success | yes | observed changes only | same as #2 |
| 4 | Watermark + Tombstone | `net_change` | `net_change` | append observations + tombstones; optional current projection | explicit tombstone | source version/position + business key | append -> dedupe -> MERGE with matched DELETE/soft-delete -> checkpoint | yes | observed changes/deletes only | current projection possible; procedural delete path remains classic fallback |
| 5 | Native CDC — Net Changes -> MERGE | `net_change` | `net_change` | append each capture window before current MERGE | explicit | CDC position + business key | append batch -> dedupe -> MERGE current | yes | net/batch history only | current-state declarative projection when appropriate |
| 6 | Native CDC — Net Changes -> APPEND | `net_change` | `net_change` | append one observed final change per key/window | explicit | batch/source position + business key | append net-change evidence -> derive current with latest-by-key | yes | net/batch history, not full transaction history | latest-by-key SCD1 projection fits well if refresh economics are good |
| 7 | Native CDC — All/Full Changes | `full_change` | `full_change` | immutable ordered change events | explicit | LSN/sequence/event identity | append events -> append-only Stream -> triggered Task -> SCD1 MERGE / SCD2 processor | yes | full if source ordering/completeness reliable | current/SCD1 projection only; SCD2 stays classic |
| 8 | Transaction Log CDC | `full_change` | `full_change` | immutable transaction-log events | explicit | LSN/SCN/log position | same as #7 | yes | full if log ordering reliable | same as #7 |
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

### Net CDC

Do not label net-change CDC as full history. If five source changes collapse into one final row before the extractor receives them, no downstream Snowflake implementation can reconstruct those four lost transitions.

### Full CDC/event

Land immutable events before reducing them to current state. A Snowflake standard Stream is a net-delta offset over a Snowflake source object; it is not the authoritative source audit log.

### Files

Use Snowflake file metadata such as filename, row number and file content key where appropriate. Snowpipe duplicate-file tracking is useful ingestion protection, but the framework does not treat it as a permanent enterprise idempotency ledger.

## Standard execution-engine policy

```text
engine = classic     # mandatory implementation and break-glass path
engine = dynamic     # optional for supported declarative current/projection logic
```

Execution engine is an implementation/deployment choice, not a business contract. Switching between classic and Dynamic Table must not change RAW semantics or the published Silver contract.

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
INCREMENTAL
FULL
ADAPTIVE
```

It intentionally does not silently default to `AUTO`. Dynamic Tables are not the framework's SCD2 implementation.

## Minimum onboarding questions

A new dataset should be classifiable from a small technical interview:

1. Is the extract current state, net change, full change, or a business event?
2. Can the source represent delete? If yes, how?
3. What is the non-null business identity?
4. What is the reliable source ordering/version/position, if any?
5. What identity makes retries idempotent?
6. What checkpoint does the source require: watermark, cursor, LSN/offset, snapshot ID or file identity?
7. Does the source permit overlap/lookback?
8. What history can the source actually guarantee?

Those answers populate the bounded RAW `capture` contract. They do not generate business SQL.
