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

New generated Snowflake object names preserve the source boundary. For example `fleet_mssql.customer` defaults to:

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

The model includes `DATASET`, `DATASET_VERSION`, `SLA_POLICY`, run ledgers, `DATASET_HEALTH`, `INCIDENT`, `REPAIR_RUN` and `VERSION_VALIDATION`.

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

esf lifecycle-sql customer pause_incident_123 \
  --source fleet_mssql \
  --action pause \
  --version v1 \
  --project-root .

esf lifecycle-sql customer decommission_2026q4 \
  --source fleet_mssql \
  --action decommission \
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

Once `silver_processing/<source>/<dataset>/` exists, normal scaffold commands change zero bytes inside it. A candidate version is a separate ownership unit under `versions/vN/`. Generated SLA/lifecycle/repair/release operation directories use the same rule.

Project initialization is also append-only. A Framework upgrade may introduce a new control migration or runbook, but rerunning `init-project` never rewrites existing project files or the domain-owned `control_plane/deploy_manifest.txt`. Use `esf control-plan` to see which known control files are missing from the repo or deploy manifest.

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

`060_policy.sql` is a commented logical-dataset SLA starter. It deliberately contains no guessed threshold. Generated code is intended to be read and changed by domain engineers.

## SCD2 and versioning

The default SCD2 implementation keeps complete history in one physical history table. Current state is represented by `WHERE IS_ACTIVE = TRUE`. Each implementation version owns independent physical objects, Stream/Task where appropriate, apply/replay procedure and validation SQL. Consumers use stable published Silver views.

Candidate flow:

```text
v1 ACTIVE
  -> scaffold-version v2
  -> deploy candidate
  -> replay/bootstrap
  -> catch up
  -> shadow
  -> validate + compare
  -> release-sql
  -> engineer reviews activate.sql / rollback.sql
```

`release-sql` generates files only. It does not perform cutover.

## SLA and health

SLA belongs to the logical dataset, not to the source manifest and not to V1/V2 implementation metadata.

Git stores reviewable policy-change SQL under `operations/sla/`; `CONTROL.SLA_POLICY` stores the currently effective policy. Supported cadence models are `CONTINUOUS`, `INTERVAL` and `SCHEDULED_DEADLINE`. Latency and freshness remain separate metrics.

`CONTROL.SLA_EVALUATION_V` exposes current policy results. `CONTROL.EVALUATE_DOMAIN_HEALTH()` refreshes `DATASET_HEALTH` and manages automatic incidents for ingestion failure, Silver pipeline failure, dbt failure and SLA violations. Repeated evaluation updates one open incident per condition; recovery resolves it.

## Dataset lifecycle

`esf lifecycle-sql` generates explicit lifecycle SQL and never executes it.

`pause` and `resume` require an explicit implementation version so the Framework never guesses which task is active. The generated script changes the relevant Task plus `CONTROL.DATASET.ENABLED` and refreshes health.

`decommission` is deliberately a **soft decommission**. It suspends known version Tasks, disables the logical dataset and marks versions retired, while preserving Bronze/Silver data, published views and control-plane audit evidence. It does not generate executable `DROP` statements.

Physical cleanup happens later in a separately reviewed retention/governance change. New projects include `docs/DOMAIN_DECOMMISSION.md` with the staged domain-level process, including consumer cutover, retention, infrastructure cleanup and repository archive/removal decisions.

## Repair

Repair starts from the latest known-good layer:

```text
Gold wrong / Silver correct   -> rebuild dbt descendants
Silver wrong / Bronze correct -> candidate version + replay
Bronze wrong                  -> repair ingestion, then replay downstream
```

`repair-plan` is read-only. `repair-sql` generates explicit SCD2 candidate replay SQL under `operations/replay/`. Engineers review and run that SQL themselves. Replay, backfill and reset remain separate concepts.

## dbt and deployment

Silver processing and dbt remain in the same domain repo so one Git SHA identifies one domain release. dbt starts from trusted Silver. The framework keeps Mart/KPI/Semantic as exploratory domain work; it provides skeletons/examples rather than auto-generating business logic.

The reusable deployment workflow executes committed control-plane SQL first, then committed Silver SQL, then dbt. Scaffolding never occurs during deployment.

## Deliberately absent

The toolkit does not contain a universal source-discovery engine, universal ingestion orchestrator, central generic SCD runtime engine, runtime metadata routing, metadata-to-runtime transformation SQL generation, deployment-time scaffolding, automatic SLA inference, one-click destructive decommission, automatic business Mart/KPI/Semantic generation, or connector-state engines for mature connectors that already own their checkpoint state.

Live Snowflake/WIF acceptance remains a separate integration gate until a configured DEV Snowflake environment is available.
