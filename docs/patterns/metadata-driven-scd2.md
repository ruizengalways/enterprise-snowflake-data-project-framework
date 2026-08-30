# Metadata-driven SCD2

## Purpose

The framework keeps human guidance separate from machine contracts.

- `docs/` is for people: intent, architecture, examples, trade-offs, and operational guidance.
- `project_schema/` is for machines: JSON Schema that defines accepted metadata shape.
- project `config/` and `contracts/` are machine-readable declarations owned by a domain repository.
- `dbt_package/macros/` contains reusable SQL generation. Domain repositories should not copy the generated SCD2 SQL.

The goal is a small domain declaration that selects a standard SCD2 behavior without hiding genuinely project-specific business logic behind a generic abstraction.

## Standard event-history contract

For an append-preserved change feed, a standard SCD2 dataset declares:

```yaml
load_strategy: scd2_merge
business_key:
  - vehicle_id
scd2:
  effective_at_column: source_updated_at
  order_columns:
    - source_updated_at
    - source_sequence
  tracked_columns:
    - status
    - depot_id
  operation_column: source_operation
  delete_values:
    - D
  late_arriving_policy: rebuild_affected_keys
```

The RAW contract remains the source-facing contract. It declares which columns exist, source change semantics, capture fidelity, checkpoint type, source ordering, and idempotency columns. Dataset metadata declares how the analytical history should behave.

## Why these fields are explicit

`business_key` identifies one logical entity. For standard SCD2 it must exactly match the RAW contract business key.

`effective_at_column` is the business-effective timestamp used for interval boundaries.

`order_columns` defines deterministic event order. It must contain the effective timestamp and preserve any ordering columns required by the RAW capture contract.

`tracked_columns` are the business attributes whose change creates a new version. Business keys are deliberately excluded. The framework computes a Snowflake `HASH(...)` over these columns for change detection; the hash is an internal comparison aid, not a unique identifier or cryptographic value.

`operation_column` and `delete_values` describe explicit tombstone events when the RAW contract exposes them.

`late_arriving_policy: rebuild_affected_keys` means a late event does not patch only the current row. The history for affected business keys is reconstructed from the append-preserved event relation so interval boundaries remain deterministic.

## dbt API

Project code should use the metadata-aware API instead of repeating key/timestamp/hash/delete arguments:

```jinja
{{ enterprise_snowflake_framework.esf_scd2_history_select_for_dataset(
    ref('stg_vehicle_status_events'),
    'vehicle_status'
) }}
```

For an incremental/recovery execution that already knows the affected key set:

```jinja
{{ enterprise_snowflake_framework.esf_scd2_rebuild_affected_keys_for_dataset_sql(
    target_relation,
    ref('stg_vehicle_status_events'),
    affected_keys_relation,
    'vehicle_status'
) }}
```

The lower-level `esf_scd2_event_history_select` and `esf_scd2_rebuild_affected_keys_sql` macros remain available for framework tests and genuinely custom implementations.

## Validation before Snowflake exists

Static validation can prove that:

- required SCD2 metadata exists for SCD2 strategies;
- referenced columns exist in the RAW contract;
- analytical and RAW business keys agree;
- effective timestamp participates in ordering;
- source-required ordering is preserved;
- tracked columns are attributes rather than keys;
- tombstone configuration is consistent with RAW change semantics;
- dbt can parse the metadata-aware SCD2 macro path offline.

This does not prove Snowflake runtime behavior. Live DEV verification is still required for transaction behavior, permissions, task/stream semantics, query plans, concurrency, retry behavior, and cross-domain authorization.

## Readability rule

Do not commit generated SQL copies into a domain repository merely to make the pipeline work. A reader should normally find:

1. source truth in `contracts/raw/<dataset>.yml`;
2. analytical behavior in `config/datasets/<dataset>.yml`;
3. a thin dbt model or orchestration call naming the dataset;
4. reusable implementation in the framework;
5. explanatory material in `docs/`.

If a dataset cannot be expressed clearly with the standard metadata, set `implementation: custom` and keep its special logic in the domain repository instead of expanding the generic contract indefinitely.
