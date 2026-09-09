# Operational control plane

The control plane standardizes operational state without becoming the data plane.

```text
DATA PLANE
BRONZE -> explicit domain Silver SQL -> SILVER -> dbt -> GOLD/SEMANTIC

CONTROL PLANE
run state
landed-data processing checkpoint
bootstrap handoff
DQ / reconciliation
reset / generation
deployment audit
observability
```

RAW contracts describe source evidence. `silver_processing/<dataset>/pipeline.yml` describes the small, reviewable contract for a domain-owned Silver implementation. Neither contract contains connector configuration or generated runtime SQL.

`PIPELINE_CHECKPOINT` can record progress over already-landed Snowflake evidence when a pipeline needs it. SQL Server LSNs, Kafka connector offsets, API cursors and similar extraction state remain with ingestion.

Domain roles use only platform-provisioned domain-scoped views/procedures. Shared `PLATFORM_CONTROL` base tables remain platform-owned and are never a convenient parameter store for arbitrary domain code.

A deployment can record Git SHA and operational evidence through explicit platform APIs, but the control plane is not the source of truth for Silver transformation SQL. That SQL is reviewed in the domain repository.
