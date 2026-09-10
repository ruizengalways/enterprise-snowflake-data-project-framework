# Input idempotency contract

## Why this contract exists

Framework 0.26 hardens generated `append + stream_task` and `scd2 + stream_task` apply/replay SQL after a real Transport-domain adoption exposed a mismatch between the reviewed RAW contract and generated batch behavior.

The RAW contract already declares an `idempotency_key`. Generated append validation also requires one Silver row per idempotency identity. Before 0.26, target-side `NOT EXISTS` checks prevented re-inserting identities already persisted, but two rows with the same identity could still arrive in the **same** Stream or replay input and both pass that check.

This is a template correctness fix, not a new runtime framework.

## Reviewed identity remains authoritative

The Framework does not infer an idempotency identity. It uses the reviewed RAW contract:

```yaml
contract:
  idempotency_key:
    - vehicle_id
    - event_timestamp
```

For append pipelines, the incoming identity is exactly the RAW `idempotency_key`.

For SCD2 event capture, the existing persistent event identity remains:

```text
RAW idempotency key + ESF_STREAM_ACTION
```

The action remains part of the SCD2 event identity so insert/delete evidence is not collapsed into one event merely because the source key is the same.

## Batch behavior in 0.26

Apply and replay now follow the same rule before writing the target/event ledger:

```text
incoming batch
  -> group by reviewed idempotency identity
  -> same identity + conflicting payload -> FAIL CLOSED
  -> same identity + identical payload   -> collapse exact duplicates to one row
  -> compare deduped input with already persisted identity
  -> write only identities not already persisted
```

A conflict raises `E_IDEMPOTENCY_CONFLICT` from generated Snowflake Scripting. The primary transaction is rolled back rather than selecting an arbitrary winning payload.

Exact duplicates may be collapsed because conflict detection has already established that all rows for the identity agree on the payload used by the generated implementation.

## Replay ordering

For append and SCD2 full replay, conflicting input is checked **before destructive candidate clearing**.

The generated flow is intentionally:

```text
stage selected Bronze evidence
  -> record REPAIR_RUN STARTED
  -> begin transaction
  -> validate incoming idempotency identities
  -> only then clear candidate state for a full replay
  -> write deduplicated evidence
  -> commit
```

This prevents an invalid replay batch from clearing candidate state before the conflict is detected.

## What this does not mean

This contract does not make the Framework a connector checkpoint manager, source deduplication service, global event registry, or runtime metadata interpreter.

It also does not redefine logical business keys. Business key, ordering columns, source timestamps and idempotency identity remain separate reviewed concepts in the RAW contract.

The Framework does not silently repair conflicting source evidence. A same-identity/different-payload conflict is evidence that the source contract or captured data must be investigated.

## Template provenance

The generated artifact contract changes only for two templates:

```text
append_stream_task  revision 2 -> revision 3
scd2_stream_task    revision 2 -> revision 3
```

Other template revisions do not advance.

`esf upgrade-plan --project-root .` reports earlier registered revisions as `UPDATE_AVAILABLE`; it remains read-only and never rewrites domain-owned SQL.

Existing domain versions stay valid source code owned by their domain. To adopt the hardened template, create/re-scaffold an ownership unit only where domain ownership rules permit it, review the generated SQL, and compare behavior before release.

## Control Plane impact

None. Framework 0.26 does not add or modify a Control migration. The released Control migration chain remains through `140_dynamic_table_observability_enrichment.sql`.
