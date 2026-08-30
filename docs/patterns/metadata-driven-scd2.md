# Metadata-driven SCD2

## Purpose

The framework keeps human guidance separate from machine contracts.

- `docs/` is for people: intent, architecture, examples, trade-offs, and operational guidance.
- `project_schema/` is for machines: JSON Schema that defines accepted metadata shape.
- project `config/` and `contracts/` are machine-readable declarations owned by a domain repository.
- `tests/fixtures/` is for deterministic machine-readable behavior fixtures.
- `dbt_package/macros/` contains reusable SQL generation. Domain repositories should not copy the generated SCD2 SQL.

The goal is a small domain declaration that selects a standard SCD2 behavior without hiding genuinely project-specific business logic behind a generic abstraction.

## Strategy-specific metadata

SCD2 snapshot and event-history pipelines share tracked business attributes, but they do not need the same operational metadata. The machine contract deliberately reflects that difference instead of forcing every strategy into one oversized shape.

A snapshot-driven dataset can stay small:

```yaml
load_strategy: scd2_snapshot
business_key:
  - vehicle_id
scd2:
  tracked_columns:
    - status
    - depot_id
```

Snapshot effective time belongs to the snapshot execution itself. The metadata-aware snapshot API therefore accepts an explicit effective-time SQL expression when the snapshot is applied.

For an append-preserved event feed, a standard event-history SCD2 dataset declares:

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

## Why the event-history fields are explicit

`business_key` identifies one logical entity. For standard SCD2 it must exactly match the RAW contract business key.

`effective_at_column` is the business-effective timestamp used for event-history interval boundaries.

`order_columns` defines deterministic event order. It must contain the effective timestamp, preserve ordering required by RAW capture, and include the non-business-key portion of RAW idempotency columns. Because history is partitioned by business key, this prevents two distinct source events for the same entity from becoming an unresolved ordering tie.

`tracked_columns` are the business attributes whose change creates a new version. Business keys are deliberately excluded. The framework computes a Snowflake `HASH(...)` over these columns for change detection; the hash is an internal comparison aid, not a unique identifier or cryptographic value.

`operation_column` and `delete_values` describe explicit tombstone events when an event-oriented RAW contract exposes them. Snapshot SCD2 does not declare these fields; disappearance is handled by snapshot comparison.

`late_arriving_policy: rebuild_affected_keys` means a late event does not patch only the current row. The history for affected business keys is reconstructed from the append-preserved event relation so interval boundaries remain deterministic.

## dbt API

Event-history project code should use the metadata-aware API instead of repeating key/timestamp/hash/delete arguments:

```jinja
{{ enterprise_snowflake_framework.esf_scd2_history_select_for_dataset(
    ref('stg_vehicle_status_events'),
    'vehicle_status'
) }}
```

For an incremental or recovery execution that already knows the affected key set:

```jinja
{{ enterprise_snowflake_framework.esf_scd2_rebuild_affected_keys_for_dataset_sql(
    target_relation,
    ref('stg_vehicle_status_events'),
    affected_keys_relation,
    'vehicle_status'
) }}
```

A snapshot pipeline uses its own wrapper:

```jinja
{{ enterprise_snowflake_framework.esf_scd2_snapshot_apply_for_dataset_sql(
    target_relation,
    ref('stg_vehicle_status_snapshot'),
    'vehicle_status_snapshot',
    "current_timestamp()"
) }}
```

The lower-level `esf_scd2_event_history_select`, `esf_scd2_rebuild_affected_keys_sql`, and `esf_scd2_snapshot_apply_sql` macros remain available for framework tests and genuinely custom implementations.

## Validation before Snowflake exists

Static validation can prove that:

- required SCD2 metadata exists for SCD2 strategies;
- snapshot metadata is not polluted with event-history-only fields;
- referenced tracked columns exist in the RAW contract;
- analytical and RAW business keys agree;
- event effective timestamp participates in ordering;
- source-required ordering is preserved;
- non-key source idempotency columns participate in within-key ordering;
- tracked columns are attributes rather than keys;
- tombstone configuration is consistent with RAW change semantics;
- dbt can parse and render the metadata-aware snapshot and event-history macro paths offline.

A separate pure-Python test oracle reads machine fixtures under `tests/fixtures/scd2/` and checks event-history semantics independently of dbt SQL generation. The fixture covers unchanged replay, attribute updates, late arrival, delete boundaries, and reinsert after delete. This gives us a useful semantic proof before a Snowflake account exists without duplicating production pipeline code into the runtime package.

This still does not prove Snowflake runtime behavior. Live DEV verification is required for transaction behavior, permissions, task/stream semantics, query plans, concurrency, retry behavior, and cross-domain authorization.

## Readability rule

Do not commit generated SQL copies into a domain repository merely to make the pipeline work. A reader should normally find:

1. source truth in `contracts/raw/<dataset>.yml`;
2. analytical behavior in `config/datasets/<dataset>.yml`;
3. a thin dbt model or orchestration call naming the dataset;
4. reusable implementation in the framework;
5. explanatory material in `docs/`;
6. machine behavior fixtures under `tests/fixtures/` when deterministic examples are useful.

If a dataset cannot be expressed clearly with the standard metadata, set `implementation: custom` and keep its special logic in the domain repository instead of expanding the generic contract indefinitely.
