# Enterprise Snowflake Data Project Toolkit

This repository is intentionally **not a universal data runtime framework**.

Its responsibility is:

```text
Framework owns project creation and reusable operating patterns.
Domain repositories own project evolution and production transformation code.
```

The toolkit creates readable project/source/dataset starters, validates contracts, provides domain-local operational-control foundations, and supplies reusable CI/CD guardrails. Generated SQL is normal source code committed to the domain repository. Deployment executes committed source; it does not regenerate production transformation SQL from metadata.

## Architecture boundary

```text
Source
  -> source-specific ingestion
  -> BRONZE
  -> Stream / readiness signal
  -> dataset-local Task
  -> dataset-local SQL / SQL procedure
  -> SILVER
  -> dbt starts from trusted Silver
  -> GOLD / Mart
  -> Semantic / KPI
```

Ingestion remains source-specific. Openflow, Snowpipe, Kafka connectors, Talend/ADF/Informatica, REST API code and scheduled loads can coexist. Source profiling/discovery is deliberately outside this framework.

## One domain repo, many sources

A domain is a repository and a Snowflake database boundary. Run `esf init-project` inside the domain repo.

```text
enterprise-snowflake-transport-analytics/
├── config/sources/
├── contracts/raw/
├── ingestion/
├── silver_processing/
├── control_plane/
├── dbt/
└── operations/
```

A domain can contain many source systems. Source is a durable organization boundary:

```text
config/sources/fleet_mssql.yml
contracts/raw/fleet_mssql/customer.yml
ingestion/fleet_mssql/
silver_processing/fleet_mssql/customer/
```

New generated Snowflake object names also preserve the source boundary. For example `fleet_mssql.customer` defaults to:

```text
BRONZE.FLEET_MSSQL_CUSTOMER
SILVER.FLEET_MSSQL_CUSTOMER_V1_HISTORY
SILVER.FLEET_MSSQL_CUSTOMER_CURRENT
```

This avoids collisions when two sources in one domain both contain a `customer` dataset. Existing domain-owned pipelines are never renamed automatically.

## Domain-local control plane

Each domain owns its own `CONTROL` schema. Do not put all domains into one shared writable control database.

`esf init-project` creates committed control-plane source:

```text
control_plane/
├── README.md
├── deploy_manifest.txt
└── sql/
    ├── 001_objects.sql
    ├── 010_observability_views.sql
    ├── 020_refresh_health.sql
    ├── 030_sla_incident_lifecycle.sql
    └── 040_health_task.sql
```

The model includes:

```text
DATASET
DATASET_VERSION
SLA_POLICY
INGESTION_RUN
PIPELINE_RUN
DBT_RUN
DATASET_HEALTH
INCIDENT
REPAIR_RUN
VERSION_VALIDATION
```

`030_sla_incident_lifecycle.sql` adds cadence-aware SLA evaluation and automatic incident lifecycle. `040_health_task.sql` creates a one-minute serverless health task. The task is created suspended and must be explicitly resumed after validation.

Cross-domain health is read-only aggregation of each domain's stable health view. A domain can be maintained or decommissioned independently.

## CLI

```bash
python -m pip install .

esf init-project --project-root .
esf control-plan --project-root .
esf add-source fleet_mssql --project-root .
esf plan --source fleet_mssql --project-root .
esf scaffold-preview customer --source fleet_mssql --project-root .
esf scaffold scd2 customer --source fleet_mssql --project-root .
esf scaffold-all --source fleet_mssql --project-root .

esf scaffold-version customer v2 --source fleet_mssql --project-root .

esf sla-sql customer freshness_v1 \
  --source fleet_mssql \
  --stage END_TO_END \
  --cadence CONTINUOUS \
  --max-freshness-seconds 600 \
  --project-root .

esf repair-plan customer --source fleet_mssql --problem silver --project-root .
esf repair-sql customer v2 --source fleet_mssql --from "2026-09-01 00:00:00" --project-root .
esf release-sql customer --source fleet_mssql --from-version v1 --to-version v2 --project-root .

esf validate --project-root .
```

There is deliberately **no `--force`**.

## Ownership rule

```text
NOT EXISTS
    -> scaffold
EXISTS
    -> DOMAIN OWNED FOREVER
```

Once `silver_processing/<source>/<dataset>/` exists, normal scaffold commands change zero bytes inside it. A candidate version is a separate ownership unit under `versions/vN/`; if that version directory exists, `scaffold-version` changes zero bytes there as well. Generated SLA/repair/release files use the same rule.

Project initialization is also append-only. A Framework upgrade may introduce a new control migration file, but rerunning `init-project` never rewrites existing project files or the domain-owned `control_plane/deploy_manifest.txt`. Use `esf control-plan` to see which known control files are missing from the repo or deploy manifest.

## New dataset implementation layout

A new dataset starter contains explicit Snowflake source-code skeletons:

```text
silver_processing/fleet_mssql/customer/
├── README.md
├── pipeline.yml
├── version.yml
├── 001_objects.sql
├── 010_apply.sql
├── 015_replay.sql
├── 020_validate.sql
├── 025_compare.sql
├── 030_task.sql
├── 040_register.sql
├── 050_publish.sql
├── 060_policy.sql
└── deploy_manifest.fragment.txt
```

`060_policy.sql` is a commented logical-dataset SLA starter. It deliberately contains no guessed threshold. For standard patterns, the rest of the starter generates version-local physical objects, a Stream where appropriate, a SQL procedure, a Task, control-plane registration and stable published views. Generated code is intended to be read and changed by domain engineers.

## SCD2 default

The default SCD2 implementation keeps complete history in one physical history table. Current state is represented by:

```sql
WHERE IS_ACTIVE = TRUE
```

Each version has its own physical history and current view, while consumers use stable published objects. A separately materialized current table is optional when performance evidence justifies it.

## Stream + Task + procedure

For append/SCD1/SCD2 starters, every implementation version owns an independent Stream and Task. This allows active and candidate versions to consume the same Bronze source independently.

```text
BRONZE
  ├── V1 Stream -> V1 Task -> V1 procedure -> V1 Silver
  └── V2 Stream -> V2 Task -> V2 procedure -> V2 Silver
```

Tasks are created suspended by Snowflake. Candidate tasks remain unpublished until engineers bootstrap/replay, catch up, compare, validate and explicitly activate them. Full-refresh/custom pipelines do not pretend that one readiness model fits every source; engineers wire schedule/AFTER/control-event logic explicitly.

## Candidate and blue/green workflow

```text
v1 ACTIVE
  -> scaffold-version v2
  -> deploy candidate objects
  -> historical replay/bootstrap
  -> catch up
  -> shadow
  -> 020_validate.sql
  -> 025_compare.sql
  -> VERSION_VALIDATION evidence
  -> release-sql
  -> engineer reviews activate.sql / rollback.sql
```

`release-sql` only generates files. It does not connect to Snowflake and never performs cutover itself.

## SLA and health

SLA belongs to the logical dataset, not to the source manifest and not to V1/V2 implementation metadata.

Git stores reviewable policy-change SQL under `operations/sla/`; `CONTROL.SLA_POLICY` stores the currently effective policy used by the evaluator. `esf sla-sql` creates a new revision file and never executes or overwrites it.

Supported cadence models are:

```text
CONTINUOUS
INTERVAL
SCHEDULED_DEADLINE
```

Latency and freshness remain separate metrics. Policy can be stage-specific across Source -> Bronze, Bronze -> Silver, Silver -> Gold and end-to-end freshness.

`CONTROL.SLA_EVALUATION_V` exposes current policy results. `CONTROL.EVALUATE_DOMAIN_HEALTH()` refreshes `DATASET_HEALTH` and manages automatic incidents for ingestion failure, Silver pipeline failure, dbt failure and SLA violations. Repeated evaluation updates one open incident per condition; recovery resolves it.

The one-minute health task uses Snowflake-managed serverless task compute rather than waking the domain transformation warehouse just to refresh health.

## Repair

Repair starts from the latest known-good layer:

```text
Gold wrong / Silver correct   -> rebuild dbt descendants
Silver wrong / Bronze correct -> candidate version + replay
Bronze wrong                  -> repair ingestion, then replay downstream
```

`repair-plan` is read-only. `repair-sql` generates explicit SCD2 candidate replay SQL under `operations/replay/`. Engineers review and run that SQL themselves. Active production objects are not modified by the generated replay script.

Replay, backfill and reset remain separate concepts.

## dbt and deployment

Silver processing and dbt remain in the same domain repo so one Git SHA identifies one domain release. dbt starts from trusted Silver. The framework keeps Mart/KPI/Semantic as exploratory domain work; it provides skeletons/examples rather than auto-generating business logic.

The reusable deployment workflow executes committed control-plane SQL first, then committed Silver SQL, then dbt. Scaffolding never occurs during deployment.

## Deliberately absent

The toolkit does not contain a universal source-discovery engine, universal ingestion orchestrator, central generic SCD runtime engine, runtime metadata routing, metadata-to-runtime transformation SQL generation, deployment-time scaffolding, automatic SLA inference, automatic business Mart/KPI/Semantic generation, or connector-state engines for mature connectors that already own their checkpoint state.

Live Snowflake/WIF acceptance remains a separate integration gate until a configured DEV Snowflake environment is available.
