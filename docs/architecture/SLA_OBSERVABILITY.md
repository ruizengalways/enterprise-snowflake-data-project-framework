# SLA and observability

## Goal

Every logical dataset must expose enough operational evidence to answer, without reading transformation code:

- Is ingestion healthy?
- Did Bronze receive the expected data?
- Did Bronze -> Silver complete?
- Is downstream dbt healthy?
- How fresh is the published dataset?
- Which SLA is currently violated?
- Which version is active/candidate?
- Is there an open incident?

## SLA dimensions

Do not collapse all service expectations into one `latency` value.

### Stage latency

Supported stages:

- SOURCE_TO_BRONZE
- BRONZE_TO_SILVER
- SILVER_TO_GOLD
- END_TO_END

Latency is the delay introduced while moving or processing data between stages.

### Freshness

Freshness is the age of the most recent business/source event represented by the published dataset relative to current time.

A pipeline can have low processing latency while still serving stale data because the source has stopped producing data. Therefore freshness and latency are separate metrics.

### Expected cadence

Different datasets require different expectation models:

- CONTINUOUS / event-driven
- INTERVAL, for example every five minutes or hourly
- SCHEDULED_DEADLINE, for example a daily snapshot due by 04:00 local time

SLA policy must preserve this distinction.

## Run evidence

### Ingestion

`INGESTION_RUN` records connector-independent evidence such as:

- status
- start/end
- source event range
- Bronze publication time
- rows received
- ingestion technology
- external run ID
- error details

### Bronze -> Silver

`PIPELINE_RUN` records:

- dataset/version
- status
- start/end
- Bronze data range
- Silver data range/publication time
- rows read/inserted/updated/deleted
- task name
- query ID
- warehouse
- failure details

### dbt

`DBT_RUN` records enough model execution evidence to determine downstream health and drive repair decisions.

## Current health state

`DATASET_HEALTH` is a current-state table, not a complete history table.

Recommended fields:

- dataset_id
- evaluated_at
- active_version
- ingestion_status
- bronze_status
- silver_status
- gold_status
- last_source_event_at
- last_bronze_at
- last_silver_at
- last_gold_at
- source_to_bronze_latency_seconds
- bronze_to_silver_latency_seconds
- silver_to_gold_latency_seconds
- freshness_seconds
- sla_status
- open_incident_count
- overall_status

Suggested overall statuses:

```text
GREEN
YELLOW
RED
PAUSED
DEVELOPMENT
```

## Health evaluation

A domain-local Snowflake task may periodically call a domain-local control procedure to refresh `DATASET_HEALTH` from:

- `DATASET`
- `SLA_POLICY`
- latest successful/failed run evidence
- open incidents

This centralization is allowed because it is operational control logic, not business transformation logic.

## Incident lifecycle

Health evaluation can open or update incidents for conditions such as:

- FRESHNESS_SLA
- LATENCY_SLA
- INGESTION_FAILURE
- PIPELINE_FAILURE
- DBT_FAILURE
- DQ_FAILURE
- RECONCILIATION_FAILURE

A sustained problem maps to one ongoing incident. Re-evaluation updates that incident; recovery resolves it.

## Dashboard contract

Each domain publishes stable dashboard-ready views from its `CONTROL` schema. The first enterprise view should be a one-row-per-dataset health surface.

Example columns:

```text
dataset
owner
criticality
active_version
candidate_version
last_source_event
last_bronze
last_silver
last_gold
freshness
sla_status
last_ingestion_status
last_pipeline_status
last_dbt_status
overall_status
open_incidents
```

A cross-domain dashboard can union these domain views, but it must not become a central runtime dependency.

## Snowflake system history

Snowflake task/query/copy history is useful for audit, enrichment, cost analysis and postmortem. Domain run ledgers remain the primary low-latency operational contract because system/account history views can have visibility delay and do not contain all domain-specific semantics.

## Ownership

SLA policy belongs to the domain. Platform-level dashboards may impose display conventions, but they should not silently change a domain's operational thresholds.
