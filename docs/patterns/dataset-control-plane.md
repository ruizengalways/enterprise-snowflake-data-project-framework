# Dataset control plane v2

The control plane standardizes operational mechanics without becoming the data plane.

```text
DATA PLANE
BRONZE -> SILVER -> GOLD

CONTROL PLANE
validated dataset config
config snapshot
run state
landed-data processing checkpoint
bootstrap handoff
DQ / reconciliation
reset / generation
observability
```

## Dataset grain

Runtime/config state is keyed by project + environment + dataset (+ generation where relevant). Datasets in one domain database can therefore use different maintenance and runtime policies without one giant database-level refresh policy.

Strategy-specific parameters remain in typed Git metadata instead of a wide nullable control table.

## Source contract versus dataset config

Raw/source contract describes source semantics and evidence fidelity. Dataset config describes downstream Snowflake maintenance semantics. Neither contains connector implementation configuration.

A connector may be Openflow, Snowpipe, Kafka, Fivetran, Airbyte, ADF or custom code; once equivalent Bronze evidence is landed, downstream Framework behavior is the same.

## Checkpoint boundary

`PIPELINE_CHECKPOINT` is for processing progress over landed Snowflake data, for example a last processed landed batch, file identity, event boundary or timestamp already present in Bronze.

It must not store or own:

```text
SQL Server LSN
Kafka connector offset
API extraction cursor
other connector-owned source position
```

Those belong to the ingestion system.

## Security boundary

Domain runtime roles do not directly mutate shared `PLATFORM_CONTROL` base tables. Platform infra exposes project-filtered views and guarded domain procedures. Framework helpers derive only those approved relation/procedure names.

## Config snapshots

Git remains desired configuration truth. A deployment snapshot records the validated dataset/raw-contract content, config SHA and Git SHA for audit and observability. The Snowflake snapshot table is not an editable parameter store.

## Custom datasets

Custom business implementation remains explicit domain code. Custom datasets may still register runs/config snapshots, use DQ/reconciliation, query tags and reset lifecycle.
