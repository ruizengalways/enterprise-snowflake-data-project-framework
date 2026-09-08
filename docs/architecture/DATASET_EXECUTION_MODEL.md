# Dataset execution model

## Purpose

The framework is metadata-driven at the **dataset/table boundary**, not at the database boundary.

A governed domain database can contain many tables with different refresh and history requirements. Each dataset independently chooses its target semantics and execution mechanism.

The design rule is:

```text
Metadata = HOW TO RUN
SQL      = WHAT THE DATA MEANS
```

Metadata must not become a second programming language for joins, filters, CASE expressions, window functions, aggregations, or business rules.

## Two independent dimensions

Dataset metadata v2 separates target semantics from execution mechanism.

### `load.strategy`

Describes the observable target behavior:

```text
full_refresh
append_only
incremental_merge
scd1
scd2
custom
```

### `load.execution.mode`

Describes how that behavior is implemented:

```text
dbt_batch
dbt_snapshot
dynamic_table
stream_task
custom
```

This prevents strategy-name explosion such as `scd2_merge`, `scd2_snapshot`, `scd2_stream_task`, and future combinations. Those legacy v1 names remain accepted during migration and are normalized internally.

## Example: one domain, independent tables

```text
TRANSPORT database

vehicle_status      strategy=scd2              mode=dbt_batch
vehicle_position    strategy=append_only       mode=dbt_batch
driver              strategy=scd1              mode=dbt_batch
depot_reference     strategy=full_refresh      mode=dbt_batch
current_trip_state  strategy=scd1              mode=dynamic_table
special_vendor_feed strategy=custom            mode=custom
```

The database is a governance/cost/data-product boundary. It is not a refresh-policy boundary.

See `examples/readable-project/config/datasets/` for a validated mixed-strategy project.

## Metadata v2 example

```yaml
schema_version: 2
dataset:
  id: vehicle_status
  owner_team: transport-data
  raw_contract: contracts/raw/vehicle_status.yml

  load:
    strategy: scd2
    execution:
      mode: dbt_batch

    business_key:
      - vehicle_id
    watermark_column: source_updated_at

    scd2:
      effective_at_column: source_updated_at
      order_columns:
        - source_updated_at
        - source_sequence
      tracked_columns:
        - status
        - depot_id
        - route_id
      operation_column: source_operation
      delete_values:
        - D
      late_arriving_policy: rebuild_affected_keys
```

There is no metadata for business joins, CASE expressions, calculations, or aggregations.

## Readable domain model

A normal batch model uses one small framework call at the top and keeps the body as ordinary SQL:

```sql
{{ enterprise_snowflake_framework.esf_apply_dataset_config('current_merge') }}

select
    entity_id,
    value,
    source_updated_at,
    source_operation,
    source_sequence,
    ingested_at
from {{ source('bronze', 'source_entity') }}
```

`esf_apply_dataset_config` configures materialization only. It must not generate business SQL.

For example:

```text
full_refresh      + dbt_batch -> dbt table
append_only       + dbt_batch -> dbt incremental append
incremental_merge + dbt_batch -> dbt incremental merge
scd1              + dbt_batch -> dbt incremental merge
scd1              + dynamic_table -> Snowflake dynamic table
custom            + custom -> framework leaves implementation explicit
```

## SCD2 is deliberately a technical primitive

SCD2 history maintenance is multi-statement state management. For full-change CDC it can require affected-key rebuilds, delete semantics, ordering and late-arrival handling.

The domain transformation should still be readable SQL, for example `stg_vehicle_status.sql`. The technical SCD2 apply step consumes that event shape through the framework SCD2 primitive.

The framework should not turn the domain model into a giant macro call that hides the event shape.

`dbt_snapshot` remains suitable when the source contract is a current-state snapshot. `stream_task` remains suitable when explicit Snowflake procedural/stream processing is required.

## Dynamic tables

Dynamic tables are an execution mechanism, not a new business load strategy. They are a good fit when a target is declaratively expressible as a SELECT and Snowflake can own dependency refresh scheduling.

The framework currently allows `dynamic_table` for `full_refresh`/current-result and `scd1` semantics. It rejects SCD2 history with dynamic tables.

The dbt package uses the caller's `target.warehouse` rather than storing environment-specific physical warehouse names in dataset metadata.

## Validation and compatibility

Schema v1 remains accepted. The framework normalizes legacy values as follows:

```text
full_refresh     -> strategy=full_refresh      mode=dbt_batch
append_only      -> strategy=append_only       mode=dbt_batch
incremental_merge-> strategy=incremental_merge mode=dbt_batch
scd1_merge       -> strategy=scd1              mode=dbt_batch
scd2_snapshot    -> strategy=scd2              mode=dbt_snapshot
scd2_merge       -> strategy=scd2              mode=dbt_batch
scd2_stream_task -> strategy=scd2              mode=stream_task
implementation=custom -> execution.mode=custom
```

Existing capture/bootstrap/SCD2 validators continue to receive a compatibility projection while new code reads the canonical `load` object.

This allows projects to migrate one dataset at a time.

## Control-plane grain

Runtime state remains keyed at dataset grain:

```text
project_code
environment
dataset_id
generation
```

Checkpoint, bootstrap, DQ, reconciliation, reset and run history therefore remain independent per table/dataset even when many datasets share one database.

## Non-goals

The framework does not define external ingestion. Openflow, Snowpipe, Kafka connectors, Fivetran, Airbyte or a custom loader can land data into Bronze as long as the repository's raw contract is satisfied.

The framework also does not encode business transformation SQL in YAML.
