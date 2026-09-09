# Current context

## Framework position

This repository is a project-creation and operations toolkit for readable Enterprise Snowflake domain repositories. It is not a universal data runtime.

The framework currently owns safe project/source scaffolding, RAW/Silver contract validation, explicit pattern templates and reusable CI/deployment workflows. Existing dataset directories are domain-owned and never overwritten by scaffolding.

## Confirmed architecture direction

### Source analysis

Source profiling/discovery will be handled separately in the future. This framework starts after engineers understand the source well enough to define RAW contracts and dataset intent.

### Ingestion

`ingestion/` is an integration boundary and example area. Projects may use Openflow, Snowpipe, Kafka connectors, external ETL/orchestrators or project-specific API ingestion. The framework does not implement a universal ingestion runtime or connector checkpoint engine.

### Bronze -> Silver

This is the framework's primary pipeline standardization area.

Preferred Snowflake-native shape:

```text
BRONZE -> Stream/readiness -> Task -> dataset-local SQL/procedure -> SILVER
```

Standard patterns remain append, full_refresh, scd1, scd2 and custom. Shared templates may generate dataset-local SQL/procedures, but there is no central metadata-driven SCD runtime.

### Domain-local control plane

Each domain owns its own `CONTROL` schema. Do not create one shared writable `PLATFORM_CONTROL` database across all domains.

Domain control-plane concerns include:

- logical dataset registry
- active/candidate version state
- SLA policy
- ingestion/pipeline/dbt run evidence
- current health state
- incidents
- version validation
- repair audit

Enterprise health dashboards may union stable health views published by each domain. The enterprise aggregation layer is read-only and is not a runtime dependency for domain pipelines.

### SCD2 default

The default SCD2 physical model is one history table containing all historical versions. Current state is represented by `IS_ACTIVE = TRUE`; a stable current view may be exposed for convenience. A separate physical current table is optional and must be justified by project performance needs.

### Versioning

Dataset implementations support active/candidate versions. Candidate versions are built in parallel, historically bootstrapped/replayed, shadow-tested and compared before lightweight cutover. Consumers use stable published Silver names and do not need to know implementation version names.

### SLA and observability

SLA is per dataset and can be stage-specific. Latency and freshness are separate metrics. Cadence may be continuous, interval or scheduled-deadline.

Domain-local run ledgers feed a materialized `DATASET_HEALTH` surface and incident lifecycle. Snowflake system history is useful for audit/enrichment but is not the only low-latency health source.

### Repair

Repair begins at the latest correct layer:

- Gold wrong / Silver correct -> rebuild dbt descendants.
- Silver wrong / Bronze correct -> build a candidate version and replay Bronze.
- Bronze wrong -> repair ingestion, then replay downstream layers.

Replay, backfill and reset remain distinct operations.

The first repair automation will generate a repair plan and explicit repair SQL/scripts for engineer review/execution. It will not autonomously execute production repair.

## Gold / KPI / Semantic

These remain exploratory domain work. The framework keeps skeletons/examples but does not auto-generate business marts, KPI SQL or semantic business models.

## Architectural guardrails

Continue to reject:

- deployment-time scaffolding
- runtime metadata routing
- metadata -> runtime transformation SQL generation
- central generic SCD runtime engines
- universal ingestion orchestration
- automatic connector state management when mature connectors already own it
- automatic business Mart/KPI/semantic generation

The control plane may centralize operational health/version/incident logic inside a domain, but must not hide dataset transformation behavior.
