# Enterprise Snowflake Data Project Toolkit

This repository is intentionally **not a data runtime framework**.

Its responsibility is simple:

```text
Framework owns project creation.
Domain repositories own project evolution.
```

The toolkit creates readable project/source/dataset starters, validates contracts, and provides reusable CI/CD guardrails. Generated SQL is ordinary source code committed to the domain repository. Deployment executes committed source; it never regenerates business SQL from metadata.

## Architecture boundary

```text
Source
  -> Ingestion
  -> BRONZE
  -> explicit domain-owned Snowflake SQL
  -> SILVER
  -> dbt starts here
  -> GOLD
  -> SEMANTIC
```

**dbt starts from trusted Silver.** Ingestion remains source-specific. SQL Server CDC, Kafka, REST APIs, Snowpipe, Snowpipe Streaming, Openflow, ADF, Fivetran, custom Python and files can all coexist without a shared ingestion runtime DSL.

## Source system is the durable organization boundary

A domain can contain many sources. Keep contracts, ingestion assets and Silver processing grouped by source system:

```text
config/sources/fleet_mssql.yml
contracts/raw/fleet_mssql/customer.yml
ingestion/fleet_mssql/
silver_processing/fleet_mssql/customer/
```

Do not organize long-lived source code around `batch_1`, `wave_2`, or similar rollout labels.

## CLI

Install the Python package and use one CLI:

```bash
python -m pip install .

esf init-project --project-root .
esf add-source fleet_mssql --project-root .
esf plan --source fleet_mssql --project-root .
esf scaffold scd2 customer --source fleet_mssql --project-root .
esf scaffold-all --source fleet_mssql --project-root .
esf validate --project-root .
```

There is deliberately **no `--force`** for scaffolding.

## Append-only scaffolding ownership

The critical rule is:

```text
NOT EXISTS
    -> scaffold
DOMAIN OWNED
    -> DOMAIN OWNED FOREVER
```

Once `silver_processing/<source>/<dataset>/` exists, Framework scaffold commands never write into that directory again. This remains true even when a standard starter file is missing. `plan`/`scaffold-all` report the directory as domain-owned and warn about incomplete starter layout, but change zero bytes.

Example growth:

```text
fleet_mssql manifest: 40 datasets
scaffold-all          -> created 40, skipped 0, overwritten 0

domain engineers edit customer/010_apply.sql

fleet_mssql manifest: 60 datasets
plan                  -> existing 40, new 20, will overwrite 0
scaffold-all          -> created 20, skipped 40, overwritten 0
```

The same rule isolates multiple sources: `esf scaffold-all --source gtfs_api` only plans/creates `gtfs_api` dataset directories and does not touch `fleet_mssql`.

## Source manifests are creation inputs, not runtime DSL

A source manifest is intentionally small:

```yaml
schema_version: 1
source:
  id: fleet_mssql
  owner: transport

datasets:
  customer:
    pattern: scd2
    raw_contract: contracts/raw/fleet_mssql/customer.yml
  orders:
    pattern: scd1
    raw_contract: contracts/raw/fleet_mssql/orders.yml
```

Supported starter patterns are `append`, `full_refresh`, `scd1`, `scd2`, and `custom`.

Source manifests do not define warehouse selection, task schedules, dbt materializations, runtime modes, connector offsets, or hidden SQL generation.

## Slim Silver pipeline metadata

RAW contracts own evidence semantics such as business key, ordering columns, idempotency key, source timestamp and delete semantics. Silver pipeline metadata does not repeat those values.

A generated SCD2 pipeline is close to:

```yaml
schema_version: 1
pipeline:
  id: customer
  pattern: scd2
  raw_contract: contracts/raw/fleet_mssql/customer.yml
  input:
    relation: BRONZE.CUSTOMER
  output:
    history: SILVER.CUSTOMER_HISTORY
    current: SILVER.CUSTOMER_CURRENT
  tracked_columns:
    - name
    - status
```

## dbt and deployment

Silver processing and dbt stay in the same domain repository so one Git SHA represents one domain release. `init-project` creates only a dbt skeleton (`models/sources`, `models/marts`, `models/semantic`, `tests`); it does not generate marts, KPIs, or semantic business logic.

A domain repository owns `silver_processing/deploy_manifest.txt`. The reusable deployment workflow validates contracts, applies exactly those committed SQL files in manifest order, then runs dbt for Gold/Semantic. No scaffolding happens during deployment.

## Deliberately absent

The toolkit does not contain a shared dbt package, shared dbt macros, custom dbt SCD materializations, `esf_apply_dataset_config`, runtime metadata routing, metadata-to-runtime SQL generation, a central SCD runtime engine, connector-specific state, or an ingestion runtime framework.

Live Snowflake/WIF acceptance is also outside the unit/CI scope unless it is explicitly run against a configured environment.
