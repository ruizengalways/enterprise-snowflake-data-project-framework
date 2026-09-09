# Current context

## Framework position

This repository is a project-creation and operations toolkit for readable Enterprise Snowflake domain repositories. It is not a universal data runtime.

The framework owns safe project/source scaffolding, RAW/Silver contract validation, explicit pattern source-code generation, domain-local control-plane foundations and reusable CI/deployment workflows. Existing ownership units are never overwritten by scaffolding.

## Domain boundary

One business domain is one domain repository and normally one domain Snowflake database per environment.

```text
enterprise-snowflake-transport-analytics
  -> DEV_TRANSPORT / UAT_TRANSPORT / PROD_TRANSPORT
```

A domain may contain many sources. The source boundary is preserved in repository paths and in newly generated Snowflake object names so same-named datasets from different sources cannot collide by default.

Example new naming:

```text
fleet_mssql.customer
  -> BRONZE.FLEET_MSSQL_CUSTOMER
  -> SILVER.FLEET_MSSQL_CUSTOMER_V1_HISTORY
  -> SILVER.FLEET_MSSQL_CUSTOMER_CURRENT
```

Existing domain-owned pipelines are not renamed automatically.

## Ingestion

`ingestion/` is an integration boundary and example area. Projects may use Openflow, Snowpipe, Kafka connectors, external ETL/orchestrators or project-specific API ingestion. The framework does not implement a universal ingestion runtime or mature connector checkpoint engines.

## Bronze -> Silver

This is the framework's primary standardization area.

Preferred Snowflake-native shape:

```text
BRONZE -> Stream/readiness -> Task -> dataset-local SQL procedure -> SILVER
```

Standard patterns remain append, full_refresh, scd1, scd2 and custom. Pattern algorithms are reused at scaffold time to generate explicit dataset-local source code. There is no central metadata-driven SCD runtime.

New dataset starters include:

```text
pipeline.yml
version.yml
001_objects.sql
010_apply.sql
015_replay.sql
020_validate.sql
025_compare.sql
030_task.sql
040_register.sql
050_publish.sql
deploy_manifest.fragment.txt
```

## Domain-local control plane

Each domain owns its own `CONTROL` schema. Do not create one shared writable `PLATFORM_CONTROL` database across all domains.

The domain control plane includes dataset/version identity, SLA policy, ingestion/pipeline/dbt run evidence, health state, incidents, version validation and repair audit. Enterprise health dashboards may union stable read-only health views from each domain.

## SCD2 default

The default SCD2 model is one physical history table per implementation version. Current state is `IS_ACTIVE = TRUE` and is exposed through a version-local current view plus a stable published current view.

Example:

```text
SILVER.FLEET_MSSQL_CUSTOMER_V1_HISTORY
SILVER.FLEET_MSSQL_CUSTOMER_V1_CURRENT
SILVER.FLEET_MSSQL_CUSTOMER_V2_HISTORY
SILVER.FLEET_MSSQL_CUSTOMER_V2_CURRENT

published:
SILVER.FLEET_MSSQL_CUSTOMER_HISTORY
SILVER.FLEET_MSSQL_CUSTOMER_CURRENT
```

A separate physical current table is optional and should be justified by performance evidence.

## Versioning and blue/green

The initial dataset implementation is v1. A candidate version is created explicitly under:

```text
silver_processing/<source>/<dataset>/versions/v2/
```

Every version gets independent physical objects, Stream/Task where appropriate, apply procedure, replay procedure and validation SQL. Creating v2 changes zero bytes in v1.

Candidate lifecycle:

```text
scaffold -> deploy -> replay/bootstrap -> catch up -> shadow -> validate -> compare -> release SQL -> explicit cutover
```

`025_compare.sql` compares the stable active published relation with the candidate and records generic evidence in `CONTROL.VERSION_VALIDATION`.

`release-sql` generates `activate.sql` and `rollback.sql` for review. `esf` never executes those files.

## SLA and observability

SLA is per logical dataset and may be stage-specific. Latency and freshness are separate metrics. Cadence can be continuous, interval or scheduled-deadline. Domain run ledgers feed `CONTROL.DATASET_HEALTH` and dashboard-ready views.

## Repair

Repair begins at the latest correct layer:

- Gold wrong / Silver correct -> rebuild dbt descendants.
- Silver wrong / Bronze correct -> build a candidate version and replay Bronze.
- Bronze wrong -> repair ingestion, then replay downstream layers.

Replay, backfill and reset remain distinct operations.

`repair-plan` is read-only. `repair-sql` currently generates explicit SCD2 candidate replay SQL for engineer review/execution and does not modify active production objects.

## Gold / KPI / Semantic

These remain exploratory domain work. The framework keeps skeletons/examples but does not auto-generate business marts, KPI SQL or semantic business models.

## Architectural guardrails

Continue to reject:

- deployment-time scaffolding
- runtime metadata routing
- metadata -> runtime transformation SQL generation
- central generic SCD runtime engines
- universal ingestion orchestration
- hidden active-version switching
- automatic production repair execution
- automatic business Mart/KPI/Semantic generation

The control plane may centralize operational health/version/incident logic inside a domain, but must not hide dataset transformation behavior.
