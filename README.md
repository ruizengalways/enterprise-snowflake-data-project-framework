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

Openflow, Snowpipe, Kafka, Fivetran, Airbyte, ADF and custom ingestion may all land the same Bronze contract. The framework does not own connector checkpoints such as SQL Server LSNs, API cursors or Kafka source offsets. Mutable framework state begins with already-landed Snowflake data.

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

The raw/source contract is also v2. It describes source semantics, grain, keys, ordering, change/delete semantics, capture fidelity and idempotency identity. It does not describe a connector implementation or connector checkpoint ownership.

## Data plane

- `BRONZE`: source-faithful landed data.
- `SILVER_STAGING`: readable typing/dedup/normalization SQL.
- `SILVER_INTERMEDIATE`: optional readable technical shaping.
- `SILVER_CANONICAL`: authoritative current state and history correctness.
- `GOLD_MARTS`: joins, KPIs, aggregations and reporting entities.
- `GOLD_SEMANTIC`: semantic preparation.

SCD2 publishes one authoritative `<entity>_history` table and a normal `<entity>_current` view. The SCD2 materialization keeps a technical landed-event ledger and rebuilds only affected business keys, so replay and late-arriving events remain deterministic without rebuilding unrelated history.

Dynamic Tables are Gold-first and use `REFRESH_MODE = ADAPTIVE` when appropriate. Stateful Silver correctness is not hidden in Dynamic Table refresh behavior.

## Framework layout

```text
project_schema/                 machine-readable contracts
src/enterprise_snowflake_framework/
                                validation/config/runtime utilities
dbt_package/macros/control/     guarded domain-scoped control-plane calls
dbt_package/macros/quality/     bounded DQ helpers
dbt_package/macros/utilities/   small compilation/config helpers
dbt_package/materializations/   justified stateful SCD materializations
snowflake/scd/                  stateful correctness policy
examples/mixed-strategy-project/
                                one project with all supported strategies
docs/                           human-readable architecture and operations
```

See `docs/architecture/HYBRID_ARCHITECTURE_V2.md`, `docs/architecture/DATASET_EXECUTION_MODEL.md`, `docs/architecture/MACRO_AUDIT.md`, and `examples/mixed-strategy-project/`.

## CI levels

CI deliberately favors focused proof over a large slow suite: schema/metadata validation, genuinely offline dbt parse + manifest/render assertions, an independent SCD2 behavior oracle, and static Snowflake/security contracts. Live Snowflake acceptance remains a separate WIF gate and must not be claimed until it actually executes successfully.
