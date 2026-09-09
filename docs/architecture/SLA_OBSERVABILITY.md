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

The control plane is domain-local. A domain owns its policies, run evidence, health state and incidents. Enterprise dashboards may union stable health views from many domains, but that aggregation is read-only and is not a runtime dependency.

## SLA policy ownership

SLA policy belongs to the logical dataset, not to a source manifest and not to an implementation version.

Git stores the reviewable policy-change history. `CONTROL.SLA_POLICY` stores the currently effective runtime state used by the evaluator and dashboards.

Use a new committed SQL revision when policy changes:

```bash
esf sla-sql customer freshness_v1 \
  --source fleet_mssql \
  --stage END_TO_END \
  --cadence CONTINUOUS \
  --max-freshness-seconds 600
```

The generated file is written under `operations/sla/<source>/<dataset>/`. `esf` never executes it and never overwrites an existing policy revision file.

A new dataset scaffold includes `060_policy.sql` as a commented starter only. The framework does not guess SLA thresholds. Candidate versions do not duplicate logical-dataset policy.

## SLA dimensions

Do not collapse all service expectations into one `latency` value.

### Stage latency

Supported stages:

- `SOURCE_TO_BRONZE`
- `BRONZE_TO_SILVER`
- `SILVER_TO_GOLD`
- `END_TO_END`

Latency is the delay introduced while moving or processing data between stages.

### Freshness

Freshness is the age of the most recent business/source event represented by the published dataset relative to current time.

A pipeline can have low processing latency while still serving stale data because the source has stopped producing data. Freshness and latency are therefore separate metrics.

### Expected cadence

Supported expectation models are:

- `CONTINUOUS` / event-driven
- `INTERVAL`, for example every five minutes or hourly
- `SCHEDULED_DEADLINE`, for example a daily snapshot due by 04:00 in `Australia/Sydney`

`INTERVAL` requires `EXPECTED_INTERVAL_SECONDS`.

`SCHEDULED_DEADLINE` requires both `DEADLINE_LOCAL_TIME` and an IANA timezone. Before the daily deadline the policy evaluates as `NOT_DUE`; after the deadline it violates if the expected stage has not published on the current local date.

## Run evidence

### Ingestion

`INGESTION_RUN` records connector-independent evidence such as status, start/end, source event range, Bronze publication time, rows received, ingestion technology, external run ID and errors.

### Bronze -> Silver

`PIPELINE_RUN` records dataset/version, status, start/end, Bronze/Silver data ranges, Silver publication time, row counts, task name, query ID, warehouse and failure details.

### dbt

`DBT_RUN` records enough model execution evidence to determine downstream health and drive repair decisions.

## SLA evaluation surfaces

`CONTROL.SLA_EVALUATION_V` evaluates every enabled SLA policy against current run evidence.

Important statuses are:

```text
PASS
VIOLATED
UNKNOWN
NOT_DUE
DISABLED
INVALID_POLICY
```

`CONTROL.SLA_VIOLATION_V` exposes only current violations for incident processing and dashboards.

## Current health state

`DATASET_HEALTH` is a current-state table, not a complete history table. It includes the active version, latest stage statuses/timestamps, stage latencies, freshness, SLA status, health reason, incident count and overall status.

Suggested overall statuses remain:

```text
GREEN
YELLOW
RED
PAUSED
DEVELOPMENT
```

The evaluator uses failures and SLA violations for `RED`; missing/invalid/unknown evidence can produce `YELLOW`; paused/development datasets remain explicit states.

## Incident lifecycle

`CONTROL.EVALUATE_DOMAIN_HEALTH()` refreshes health and manages automatic incidents for:

- `INGESTION_FAILURE`
- `PIPELINE_FAILURE`
- `DBT_FAILURE`
- `SLA_VIOLATION`

An automatic condition has a stable incident key composed from dataset, incident type and stage. Repeated evaluation updates the same open incident rather than creating a new one every minute. When the automatic condition disappears, the incident is resolved.

The evaluator must not automatically resolve unrelated/manual incident types such as DQ, reconciliation or human-created investigations.

## Health task

New projects include `CONTROL.EVALUATE_DOMAIN_HEALTH_TASK`, scheduled every minute using Snowflake-managed serverless task compute. It is created suspended by Snowflake and must be explicitly resumed only after the domain validates its control objects and policies.

This avoids waking each domain's transformation warehouse every minute merely to evaluate health.

## Dashboard contract

Each domain publishes stable dashboard-ready views from its `CONTROL` schema. The first enterprise surface is one row per logical dataset and should expose dataset identity/owner/criticality, active/candidate version, latest stage timestamps, freshness, SLA status/reason, latest run statuses, overall health and open incidents.

A cross-domain dashboard can union these views across 20 or more domain databases. It remains a read-only reporting concern and does not become a shared writable control plane.

## Control-plane upgrades

`init-project` is append-only. When a newer Framework introduces a new control migration/task, rerunning `esf init-project` creates missing files but never rewrites an existing `control_plane/deploy_manifest.txt`.

Use:

```bash
esf control-plan --project-root .
```

to compare Framework-known control SQL, files currently present in the domain repo, and entries in the domain-owned deploy manifest. The command is read-only. Engineers explicitly review and add new migrations to the manifest in their domain PR.

## Snowflake system history

Snowflake task/query/copy history remains useful for audit, enrichment, cost analysis and postmortem. Domain run ledgers remain the primary low-latency operational contract because system/account history does not contain all domain-specific semantics and can have visibility delay.

## Guardrails

SLA/health metadata is operational control only. It must not become a runtime router that decides whether a dataset uses SCD1, SCD2, append or full refresh. Transformation behavior remains explicit in the committed dataset-local Task/procedure/SQL.
