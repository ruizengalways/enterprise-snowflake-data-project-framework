# RAW contract authoring

## Purpose

RAW contracts are the reviewed boundary between source understanding and the Snowflake pipeline implementation.

The Framework deliberately does **not** discover source systems, infer business keys, choose SCD1/SCD2, or decide CDC/delete semantics. Those decisions come from source evidence and engineering judgement. A separate source-analysis/profiling toolkit may help later, but it is optional and not a dependency of this repository.

## Two-stage authoring gate

Use a draft area for incomplete work:

```text
contracts/drafts/<source>/<dataset>.yml
```

Only reviewed and valid contracts are promoted into:

```text
contracts/raw/<source>/<dataset>.yml
```

`esf validate` only treats `contracts/raw/` as production contract input. A draft can therefore contain explicit TODO values without breaking unrelated project validation.

## Workflow

```text
source evidence / engineer understanding
        ↓
esf raw-contract-draft
        ↓
contracts/drafts/<source>/<dataset>.yml
        ↓
engineer edits every semantic field
        ↓
esf raw-contract-finalize
        ↓
schema + semantic validation
        ↓
contracts/raw/<source>/<dataset>.yml
        ↓
esf add-dataset
        ↓
esf plan / scaffold-preview / scaffold
```

Example:

```bash
esf raw-contract-draft customer \
  --source fleet_mssql \
  --project-root .

# Edit contracts/drafts/fleet_mssql/customer.yml.

esf raw-contract-finalize customer \
  --source fleet_mssql \
  --project-root .

esf add-dataset customer \
  --source fleet_mssql \
  --pattern scd2 \
  --project-root .
```

Finalization moves the exact reviewed draft bytes into `contracts/raw/`; it does not rewrite the YAML. If the formal RAW contract already exists, finalization is a no-op and never overwrites it.

## Human decisions that must be resolved

The starter intentionally leaves explicit TODO values for decisions such as:

- row grain
- business key
- landed Bronze columns and Snowflake-compatible types
- source/event timestamp, when one genuinely exists
- snapshot vs append vs CDC semantics
- operation/sequence/delete semantics
- capture fidelity
- deterministic ordering
- idempotency key
- breaking-change policy

A source primary key is evidence, not automatically the business key. A column named `updated_at` is evidence, not automatically the event-ordering/source timestamp. The Framework does not make those substitutions for the engineer.

## Finalization validation

`raw-contract-finalize` fails closed when:

- TODO/REPLACE_ME values remain in parsed YAML values;
- the document violates `raw_contract.schema.json`;
- business-key, ordering, timestamp, idempotency, or CDC columns are not declared consistently;
- nullable business keys are declared;
- CDC sequence requirements are inconsistent;
- `source_system` does not match the source boundary.

On failure, the draft remains in place and no formal RAW contract is created.

## Ownership

The ownership rule continues to apply:

```text
missing draft  -> create once
existing draft -> engineer-owned; no overwrite

missing formal contract + valid draft -> explicit promotion
existing formal contract               -> domain-owned; no overwrite
```

Changing an already-finalized RAW contract is a normal reviewed Git change owned by the domain. The Framework does not silently regenerate or synchronize it from discovery metadata.

## Out of scope

This authoring workflow is not:

- source profiling;
- catalog inspection;
- a universal source connector;
- automatic schema synchronization;
- automatic pattern selection;
- automatic business-key inference;
- runtime metadata routing.

Those boundaries keep the production contract readable, reviewable, and domain-owned.
