# Enterprise Snowflake Data Project Framework v2

A small technical framework for Snowflake domain repositories.

> **Metadata = HOW TO RUN**  
> **SQL = WHAT THE DATA MEANS**

This is a breaking redesign. There is no schema v1 support, no `load_strategy`, no compatibility aliases, and no migration bridge.

## Ownership boundary

```text
External source -> ingestion -> BRONZE | SILVER -> GOLD -> semantic
                                     framework starts here
```

Openflow, Snowpipe, Kafka, Fivetran, Airbyte, ADF and custom ingestion may all land the same Bronze contract. The framework does not own connector checkpoints such as SQL Server LSNs or Kafka source offsets. Its runtime state begins with already-landed Snowflake data.

## Dataset metadata

Three independent axes describe a dataset:

```yaml
load:
  strategy: scd2
materialization:
  type: table
runtime:
  mode: dbt
```

Load strategies are `full_refresh`, `append_only`, `incremental_merge`, `scd1`, `scd2`, and `custom`. Materialization and runtime are intentionally separate so names like `scd2_stream_task` do not exist.

## Data plane

- `BRONZE`: source-faithful landed data.
- `SILVER_STAGING`: readable typing/dedup/normalization SQL.
- `SILVER_INTERMEDIATE`: optional readable technical shaping.
- `SILVER_CANONICAL`: authoritative current state and history correctness.
- `GOLD_MARTS`: joins, KPIs, aggregations and reporting entities.
- `GOLD_SEMANTIC`: semantic preparation.

SCD2 publishes one authoritative `<entity>_history` table and a normal `<entity>_current` view. Gold reads the current view instead of repeating `where is_current = true`.

Dynamic Tables are Gold-first and use `REFRESH_MODE = ADAPTIVE` when appropriate. Stateful SCD2 history uses the dedicated Snowflake/dbt materialization instead.

## Framework layout

```text
project_schema/                 machine-readable contracts
src/enterprise_snowflake_framework/
                                metadata validation/config snapshots/runtime utilities
dbt_package/macros/control/     guarded domain-scoped control-plane calls
dbt_package/macros/quality/     bounded DQ helpers
dbt_package/macros/utilities/   small compilation/config helpers
dbt_package/materializations/   justified stateful materializations only
snowflake/scd/                  stateful correctness policy
examples/mixed-strategy-project/
                                one database/project with all supported strategies
docs/                           human-readable architecture and operating guidance
```

See `docs/architecture/HYBRID_ARCHITECTURE_V2.md`, `docs/architecture/MACRO_AUDIT.md`, and `examples/mixed-strategy-project/`.

## CI levels

CI deliberately favors focused proof over a large slow suite: metadata/schema validation, offline dbt parse/compile, an independent SCD2 behavior oracle, and static Snowflake SQL/security contracts. Live Snowflake acceptance remains a separate WIF gate and must not be claimed until it actually runs successfully.
