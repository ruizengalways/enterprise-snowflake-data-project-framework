# Hybrid Snowflake Architecture v2

This repository uses one rule to keep the framework understandable:

```text
Metadata = HOW TO RUN
SQL      = WHAT THE DATA MEANS
```

## Boundary

```text
External sources -> ingestion -> BRONZE | SILVER -> GOLD -> semantic
                                   ^ boundary owned by this framework
```

Openflow, Snowpipe, Kafka, Fivetran, Airbyte, ADF and custom ingestion are outside the framework. Source connector positions such as SQL Server LSNs and Kafka offsets are not framework checkpoints. Framework checkpoints begin after landed Snowflake data exists.

## Layers

- `BRONZE`: source-faithful landed data.
- `SILVER_STAGING`: readable typing, naming and dedup SQL.
- `SILVER_INTERMEDIATE`: readable technical shaping only when needed.
- `SILVER_CANONICAL`: authoritative state/history correctness, including SCD1/SCD2.
- `GOLD_MARTS`: business joins, KPIs, aggregates and reporting entities.
- `GOLD_SEMANTIC`: semantic preparation.

Silver is the **data correctness layer**. Gold is the **business derivation layer**.

## Three orthogonal metadata axes

`load.strategy` describes maintenance semantics. `materialization.type` describes the Snowflake object. `runtime.mode` describes who runs it. They are intentionally not combined into names such as `scd2_stream_task`.

Gold Dynamic Tables are a preferred declarative option when they fit. Stateful Silver SCD2 history is not maintained by a Dynamic Table by default.

## SCD2 consumer contract

```text
SILVER_CANONICAL.<ENTITY>_HISTORY
  -> historical consumers
  -> <ENTITY>_CURRENT view
       -> GOLD
```

The history implementation is authoritative. The current object is a normal view filtering `is_current = true`, so Gold does not repeat that predicate.

## Custom is first-class

A dataset can choose `custom` independently on load, materialization or runtime. Custom implementations still reuse observability, query tags, config snapshots, deployment, DQ and reset lifecycle, but the framework does not attempt to encode business SQL in metadata.

## Compute abstraction

Dataset metadata names logical workloads such as `transform`, not physical warehouses. Platform/environment mapping resolves `(domain, environment, workload)` to the physical warehouse.

## Non-goals

Metadata is not a SQL DSL. JOIN, CASE, filters, GROUP BY, window functions and business expressions belong in domain SQL.
