# Input idempotency and replay identity contract

## Why this contract exists

Real Transport-domain adoption exposed two related generated-template correctness defects after the planned Framework architecture roadmap was complete.

Framework 0.26 fixed **batch idempotency** for generated `append + stream_task` and `scd2 + stream_task` apply/replay SQL. Framework 0.27 then fixed a narrower **SCD2 replay identity** problem for retained full-change Bronze evidence.

These are correctness fixes to generated source code, not a new runtime abstraction.

## Reviewed RAW declarations remain authoritative

The Framework does not infer an idempotency identity, delete meaning or event ordering. It uses the reviewed RAW contract.

Example append identity:

```yaml
contract:
  idempotency_key:
    - vehicle_id
    - event_timestamp
```

For append pipelines, the incoming identity is exactly the RAW `idempotency_key`.

For SCD2 event capture, the persistent event identity remains:

```text
RAW idempotency key + ESF_STREAM_ACTION
```

`ESF_STREAM_ACTION` represents the physical row action observed or synthesized for the Silver event ledger. It is not the same concept as a source-system tombstone operation column.

## Batch behavior introduced in 0.26

Before 0.26, target-side `NOT EXISTS` checks prevented re-inserting identities already persisted, but two rows carrying the same identity could arrive in the **same** Stream or replay input and both pass that target check.

Apply and replay now follow the same batch rule before writing the target/event ledger:

```text
incoming batch
  -> group by reviewed idempotency identity
  -> same identity + conflicting payload -> FAIL CLOSED
  -> same identity + identical payload   -> collapse exact duplicates to one row
  -> compare deduped input with already persisted identity
  -> write only identities not already persisted
```

A conflict raises `E_IDEMPOTENCY_CONFLICT` from generated Snowflake Scripting. The primary transaction rolls back rather than selecting an arbitrary winning payload.

Exact duplicates may be collapsed because conflict detection has already established that rows for the identity agree on the generated payload.

### NULL-safe persisted identity comparison

RAW contract v2 does not require every `idempotency_key` component to be `nullable=false`. Framework 0.26 therefore did **not** retroactively invalidate otherwise reviewed contracts merely because one idempotency component is nullable.

Generated target/event-ledger comparisons use `IS NOT DISTINCT FROM`. Two NULL values therefore compare as the same identity instead of bypassing the persisted-row guard through ordinary SQL `NULL = NULL` semantics.

### Conflict payload signature

Conflict detection compares a canonical JSON representation of the generated payload:

```text
TO_JSON(ARRAY_CONSTRUCT_KEEP_NULL(...payload columns...))
```

This preserves NULL positions and avoids making correctness depend on a finite hash collision domain. Hashes may still be used elsewhere for existing event/state evidence, but they are not the authority for deciding whether two same-identity incoming payloads conflict.

## Replay ordering safety

For append and SCD2 full replay, conflicting input is checked **before destructive candidate clearing**.

```text
stage selected Bronze evidence
  -> record REPAIR_RUN STARTED
  -> begin transaction
  -> validate incoming idempotency identities
  -> only then clear candidate state for a full replay
  -> write deduplicated evidence
  -> commit
```

An invalid replay batch therefore does not clear candidate state before the conflict is detected.

## SCD2 retained-evidence replay identity — 0.27

The Transport `vehicle_status` RAW contract is `full_change` evidence with a tombstone operation such as:

```text
SOURCE_OPERATION = 'D'
```

The tombstone is a **retained Bronze row**. Its source delete meaning is encoded by the reviewed `operation_column` and `delete_values`.

Framework 0.26 replay incorrectly converted such a retained tombstone row into synthetic:

```text
ESF_STREAM_ACTION = 'DELETE'
```

That mixed two different concepts:

```text
source-system delete semantics  -> RAW operation column / delete values
Snowflake Stream row action     -> physical change made to the Bronze table
```

If the retained Bronze row originally entered the table as an INSERT, live Stream processing records `ESF_STREAM_ACTION = 'INSERT'`. Replaying the same retained source event as `DELETE` gives the same source event a different event-ledger identity.

Framework 0.27 fixes this by replaying retained Bronze evidence rows as:

```text
ESF_STREAM_ACTION = 'INSERT'
ESF_STREAM_ISUPDATE = FALSE
```

The source tombstone still closes SCD2 history because generated history logic independently evaluates the reviewed operation column/delete values. A tombstone remains a delete boundary and is not emitted as an active SCD2 row.

This preserves replay identity without changing business delete semantics.

## What this does not mean

This contract does not make the Framework a connector checkpoint manager, source deduplication service, global event registry or runtime metadata interpreter.

It does not redefine business keys. Business key, ordering columns, source timestamp, source delete semantics and idempotency identity remain separate reviewed concepts in the RAW contract.

The Framework does not silently repair conflicting source evidence. Same-identity/different-payload input is evidence that the source contract or captured data needs investigation.

## Template provenance

Framework 0.26 advanced the two templates whose batch apply/replay artifacts changed:

```text
append_stream_task  revision 2 -> revision 3
scd2_stream_task    revision 2 -> revision 3
```

Framework 0.27 changes only SCD2 replay semantics:

```text
append_stream_task  current revision 3
scd2_stream_task    revision 3 -> current revision 4
```

SCD1, full-refresh, Dynamic Table and custom template revisions do not advance for these fixes.

`esf upgrade-plan --project-root .` remains read-only. A registered SCD2 revision 3 reports `UPDATE_AVAILABLE` under Framework 0.27; an append revision 3 remains `CURRENT`. The Framework never rewrites domain-owned SQL in place.

An unmerged shadow scaffold can be discarded and regenerated before it becomes domain-owned history. A merged/owned implementation should instead adopt a new explicitly reviewed version.

## Control Plane impact

None. Framework 0.26 and 0.27 add no Control migration. The released Control migration chain remains through `140_dynamic_table_observability_enrichment.sql`.
