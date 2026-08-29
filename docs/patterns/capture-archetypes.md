# Reusable Snowflake Capture Archetypes

This catalog maps common enterprise source-capture patterns to a small reusable set of Snowflake-native implementations.

The contract is deliberately technical. Source-specific business semantics remain explicit in the project repository.

## Design rule

Every pattern has a **classic Snowflake** implementation. Dynamic Tables are optional accelerators/alternate execution engines, never the only production path.

```text
classic baseline
  TABLE
  STREAM where useful
  TASK / triggered TASK / task graph
  MERGE / INSERT / DELETE
  Snowflake Scripting where needed

optional
  DYNAMIC TABLE
```

## Common metadata carried into Bronze

Use the subset that applies to the source:

```text
_esf_batch_id
_esf_ingested_at
_esf_source_system
_esf_snapshot_id
_esf_snapshot_at
_esf_source_operation
_esf_source_sequence
_esf_event_id
_esf_file_name
_esf_file_content_key
_esf_file_row_number
_esf_record_hash
```

Do not fabricate source ordering. `_esf_source_sequence` exists only when the source provides a reliable order/position.

---

## Archetype A — Snapshot

### Source examples

- full table extract
- daily CSV export containing the complete entity
- API full listing

### Authoritative Bronze

Append every snapshot batch:

```text
BRONZE_<ENTITY>_SNAPSHOT
  snapshot_id
  snapshot_at
  batch_id
  business_key...
  payload columns...
  record_hash
  ingested_at
```

Do not make an overwrite/current table the only Bronze copy when delete inference, SCD2, reconciliation or recovery is required.

### Classic current projection

```text
snapshot append table
  -> task/dbt model selects latest complete snapshot
  -> MERGE or transactional replace into BRONZE_<ENTITY>_CURRENT
```

### Classic diff

Compare snapshot N against N-1 on the business key and record hash:

```text
N only          -> INSERT
N and N-1 hash differs -> UPDATE
N-1 only        -> inferred DELETE
```

Materialize the diff as append-only evidence before applying it to current/SCD targets.

### Dynamic Table option

A Dynamic Table may expose the latest snapshot/current projection or a declarative diff when the query incrementally refreshes efficiently.

Do not rely on it as the only history store. Snapshot retention remains in a normal table.

### Silver

- SCD1: latest snapshot/current projection.
- SCD2: snapshot-grain history. Changes that happen multiple times between snapshots cannot be reconstructed.

---

## Archetype B — Watermark / Lookback

### Source examples

- `updated_at > last_watermark`
- timestamp plus overlap window
- monotonically increasing source version

### Authoritative Bronze

Preferred when replay/history matters:

```text
append observed source versions
```

A current MERGE table can be maintained alongside the append evidence.

### Checkpoint

Runtime control state stores the last successful source watermark/version.

For lookback:

```text
next_extract_start = last_successful_watermark - lookback_interval
```

The framework must not advance the checkpoint until the target transaction is successful.

### Deduplication

Use:

```text
business key
+ source timestamp/version
+ deterministic tie-breaker when required
```

Never dedupe only by ingestion timestamp.

### Classic implementation

```text
landing/observations
 -> QUALIFY ROW_NUMBER over source key/version
 -> MERGE current target
 -> commit
 -> update checkpoint
```

### Dynamic Table option

Useful for declarative latest-row/current projections when incremental refresh is performant.

Checkpoint extraction itself remains explicit; Dynamic Tables do not replace the external/source watermark contract.

### Silver

- SCD1: reliable for captured rows.
- SCD2: observed-version history only.
- Delete: unavailable unless the source supplies delete semantics separately.

---

## Archetype C — Net Change / Tombstone

### Source examples

- update extract + tombstone
- CDC API returning one final row per key per polling window
- native CDC net-change mode

### Authoritative Bronze

Append each captured net-change batch before merging current state:

```text
batch_id
business_key
operation/tombstone
source position/version
payload
```

This preserves what the source actually delivered while acknowledging that intermediate changes may already have been collapsed upstream.

### Classic implementation

```text
append batch
 -> dedupe by source position + business key
 -> MERGE SCD1/current
      matched DELETE/tombstone -> DELETE or soft-delete
      matched update           -> UPDATE
      not matched insert       -> INSERT
```

A standard Snowflake Stream may trigger downstream processing, but it does not improve source change fidelity.

### Dynamic Table option

Dynamic Table current projections are possible for declarative logic. Use classic Task/MERGE when explicit delete/upsert logic, retries or transaction boundaries matter.

### Silver

- SCD1: yes.
- SCD2: batch/net-change fidelity only; not full transaction history.

---

## Archetype D — Full Change / Event

### Source examples

- native CDC all changes
- transaction log CDC
- Debezium/Kafka
- Delta Change Data Feed
- business event streams

### Authoritative Bronze

Always append immutable source events.

Typical ordering/idempotency identities:

```text
LSN / SCN / log position
source sequence
event id
Kafka topic + partition + offset
Delta commit version + row identity
```

### Important Snowflake Stream rule

A Snowflake standard Stream is a net-delta consumer between offsets, not an audit log. Do not land full CDC into a mutable current table and expect a Stream on that table to recreate every source transition.

Land events first; optionally put an append-only Stream on the event table to drive processing.

### Classic SCD1

```text
append event table
 -> append-only stream
 -> triggered task
 -> order/dedupe source events
 -> MERGE current target
```

### Classic SCD2

Process ordered events by business key and source sequence. Handle insert/update/delete explicitly and preserve source event ordering in test fixtures.

### Dynamic Table option

Good for declarative projections over immutable event evidence when query shape and refresh economics are acceptable.

Do not use a Stream on a Dynamic Table for full audit history; multiple state changes can collapse into net changes between refresh/consumption points.

### Silver

- SCD1: yes.
- SCD2: full fidelity when source ordering and event completeness are reliable.

---

## Archetype E — Snapshot Diff

Snapshot Diff is the derived change-capture form of Archetype A.

### Classic implementation

```text
append snapshot N
 -> identify previous complete snapshot N-1
 -> FULL OUTER JOIN on business key
 -> classify INSERT / UPDATE / DELETE
 -> append derived diff
 -> consume diff into SCD1/SCD2
```

Use record hashes only as an optimization/classifier; business keys remain the join identity.

### Dynamic Table option

Possible as a declarative diff/current layer. Keep normal-table snapshots so the logic can be rebuilt without relying on Dynamic Table retention or refresh state.

### Fidelity

SCD2 is exact only at snapshot boundaries.

---

## Archetype F — API Cursor / Incremental Files

### API cursor

Runtime state:

```text
cursor
batch id
last successful completion
```

Land API responses/events before advancing the cursor. Use event/business identity supplied by the API for idempotency.

### File incremental

Preferred Snowflake-native components:

```text
stage
+ Snowpipe or COPY INTO
+ file metadata columns
+ normal Bronze table
```

Persist useful file metadata:

```text
METADATA$FILENAME
METADATA$FILE_ROW_NUMBER
METADATA$FILE_CONTENT_KEY
METADATA$FILE_LAST_MODIFIED
METADATA$START_SCAN_TIME
```

File identity for framework dedupe/reconciliation should include file path/name plus content key when modified-file handling matters. Snowpipe's built-in duplicate-file protection is useful but must not be treated as a permanent enterprise idempotency ledger because its behavior/history is pipe-scoped and time-bounded.

A directory table can expose `RELATIVE_PATH`, `MD5`, `ETAG`, size and last-modified metadata when file discovery/reconciliation needs it.

### Dynamic Table option

Useful downstream of the landed file/API evidence, not as a replacement for cursor/file-ingestion state.

---

# SCD capability matrix

| Capture fidelity | Delete knowledge | SCD1 | SCD2 guarantee |
|---|---|---:|---|
| current state / watermark | none | yes | observed updates only; no reliable deletes |
| current state + tombstone | tombstone | yes | observed updates/deletes only |
| net change | explicit delete | yes | one net state per capture window |
| full change | explicit/source defined | yes | full ordered history when source sequence is reliable |
| full event | event defined | yes | complete business event history; entity SCD2 depends on event semantics |
| snapshot | inferred diff | yes | snapshot-boundary history |

The framework must reject claims that exceed this matrix.

# Dynamic Table policy

Use Dynamic Tables only when all of the following hold:

1. the transformation is primarily declarative SQL;
2. supported incremental constructs fit the query;
3. refresh volume is economical;
4. reinitialization behavior is acceptable;
5. the same business contract can be produced by the classic implementation;
6. monitoring proves target lag and refresh duration are within SLO.

Production guidance:

```text
prefer explicit REFRESH_MODE
INCREMENTAL -> when change volume/query shape suits it
FULL        -> when large change volume or unsupported incremental constructs make full scan clearer
ADAPTIVE    -> optional for mixed append/bulk patterns after testing
AUTO        -> exploration, not the framework default
```

If a Dynamic Table has a defect or performance regression, switch execution engine without changing the RAW/Silver contract.

# Retry / recovery baseline

Classic Task graphs can use:

```text
TASK_AUTO_RETRY_ATTEMPTS
SUSPEND_TASK_AFTER_NUM_FAILURES
EXECUTE TASK ... RETRY LAST
finalizer task
TASK_HISTORY / COMPLETE_TASK_GRAPHS
```

Triggered Tasks can use `WHEN SYSTEM$STREAM_HAS_DATA(...)` so unpredictable arrival does not require frequent warehouse polling.

Recovery remains deterministic: replay Bronze evidence from a checkpoint/batch/source position rather than manually editing derived production data.
