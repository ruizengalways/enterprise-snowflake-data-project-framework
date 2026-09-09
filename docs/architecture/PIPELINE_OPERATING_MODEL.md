# Pipeline operating model

## Purpose

This framework standardizes how a domain repository creates, operates, versions, observes and repairs Source -> Bronze -> Silver pipelines without becoming a universal ingestion or transformation runtime.

The primary unit of operation is a logical dataset, not a physical table.

```text
source-specific ingestion
        |
        v
      BRONZE
        |
 stream / readiness event
        |
        v
 dataset-local task
        |
        v
 dataset-local SQL / procedure
        |
        v
      SILVER
        |
        v
       dbt
        |
        v
   MART / GOLD
```

## Repository boundary

The framework owns project creation and reusable templates. Once a dataset directory exists, the domain owns it forever. Framework upgrades must not overwrite domain-owned SQL.

Source profiling and source discovery are outside this repository. A separate profiling toolkit may be created later. The data-project framework starts after engineers understand the source well enough to define a RAW contract and dataset intent.

## Ingestion boundary

`ingestion/` is an integration area, not a framework runtime. A project may use Snowflake Openflow, Snowpipe, Kafka connectors, Talend, ADF, API workers, scheduled COPY operations or other enterprise tooling.

The framework may provide examples and operational interfaces, but it does not reimplement connector state such as SQL Server LSNs or Kafka offsets.

API cursor state may be stored in a domain control plane when the domain itself owns the API ingestion worker.

## RAW contracts

RAW contracts record accepted source evidence needed by downstream processing, including business keys, ordering, idempotency, source timestamps, delete semantics and capture fidelity.

They are inputs to developer-time scaffolding and validation. They are not interpreted at runtime to generate transformation SQL.

## Bronze -> Silver execution

The default Snowflake-native operating model is:

```text
BRONZE
  |
  +-- stream when change-driven
  +-- readiness/control event when batch-driven
  |
  v
TASK
  |
  v
DATASET-LOCAL APPLY SQL / PROCEDURE
  |
  v
SILVER
```

Supported standard patterns remain:

- append
- full_refresh
- scd1
- scd2
- custom

Pattern reuse is implemented by scaffold templates. Generated code is committed and becomes domain-owned. There is no central generic SCD runtime engine and no metadata-driven runtime router.

## SQL and procedures

For large transformations, prefer set-based Snowflake SQL. SQL stored procedures are appropriate when a pipeline needs multiple statements, logging, exception handling or explicit sequencing. Python stored procedures are reserved for cases where procedural Python materially improves the implementation; row-by-row Python processing is not the default for large data.

## Gold, KPI and semantic layers

Gold development is deliberately exploratory. The framework keeps dbt skeletons and examples, but does not auto-generate business marts, KPI definitions or semantic business models.

A typical project progresses:

```text
trusted Silver
  -> understand grain and relationships
  -> build domain marts
  -> confirm business definitions
  -> define KPIs / semantic models
```

## Four operating planes

### Definition and release plane

Git, RAW contracts, source manifests, dataset implementation, version metadata and SLA policy.

### Execution plane

Ingestion technology, Bronze, Streams, Tasks, dataset-local procedures/SQL, Silver and dbt.

### Observability plane

Domain-local run ledgers, health state, SLA evaluation, incidents and dashboard-ready views.

### Repair plane

Repair planning, generated repair SQL, replay, backfill, reset, candidate-version rebuild and downstream dbt rebuild guidance.

## Non-goals

This framework does not provide:

- universal source profiling or discovery
- universal ingestion orchestration
- SQL Server CDC state management when a connector owns it
- Kafka offset management
- a central SCD runtime engine
- metadata -> runtime SQL generation
- runtime metadata routing
- deployment-time scaffolding
- business mart / KPI / semantic auto-generation
- shared business transformation dbt materializations

## Core principles

1. Generated once, domain-owned forever.
2. Production transformation SQL remains explicit and reviewable in Git.
3. The control plane manages operational state; it does not interpret business transformations.
4. Different ingestion technologies may coexist in one domain.
5. Each logical dataset must be operable: owner, version, SLA, health, run history, incidents and repair history.
6. Bronze should be retained and auditable enough to support replay where the source capture mode permits it.
7. Repair starts from the most recent layer known to be correct.
8. Version upgrades prefer parallel candidate build, shadow validation and lightweight cutover.
9. Cross-domain observability is aggregation of domain health, not a central runtime control database.
