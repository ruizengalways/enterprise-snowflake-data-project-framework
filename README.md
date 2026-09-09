# Enterprise Snowflake Data Project Toolkit

This repository is intentionally **not a data runtime framework**.

Its responsibility is simple:

```text
Framework owns project creation and reusable operating patterns.
Domain repositories own project evolution and production transformation code.
```

The toolkit creates readable project/source/dataset starters, validates contracts, provides domain-local operational-control foundations, and supplies reusable CI/CD guardrails. Generated SQL is ordinary source code committed to the domain repository. Deployment executes committed source; it never regenerates business SQL from metadata.

## Architecture boundary

```text
Source
  -> Ingestion
  -> BRONZE
  -> Stream / readiness signal
  -> dataset-local Task
  -> explicit domain-owned Snowflake SQL / procedure
  -> SILVER
  -> dbt starts here
  -> GOLD
  -> SEMANTIC
```

**dbt starts from trusted Silver.** Ingestion remains source-specific. SQL Server CDC, Kafka, REST APIs, Snowpipe, Snowpipe Streaming, Openflow, ADF, Talend, custom Python and files can all coexist without a shared ingestion runtime DSL.

Source profiling/discovery is deliberately outside this framework and can be handled by a separate analysis toolkit.

## Source system is the durable organization boundary

A domain can contain many sources. Keep contracts, ingestion assets and Silver processing grouped by source system:

```text
config/sources/fleet_mssql.yml
contracts/raw/fleet_mssql/customer.yml
ingestion/fleet_mssql/
silver_processing/fleet_mssql/customer/
```

Do not organize long-lived source code around `batch_1`, `wave_2`, or similar rollout labels.

## Domain-local control plane

Each domain owns its own `CONTROL` schema in its domain database context. Do not use one shared writable `PLATFORM_CONTROL` runtime database for every domain.

`esf init-project` now creates a committed control-plane skeleton:

```text
control_plane/
├── README.md
├── deploy_manifest.txt
└── sql/
    ├── 001_objects.sql
    ├── 010_observability_views.sql
    └── 020_refresh_health.sql
```

The first control-plane contract includes logical dataset/version state, SLA policy, ingestion/Silver/dbt run ledgers, current dataset health, incidents, version validation and repair audit.

Cross-domain health is read-only aggregation of each domain's stable `CONTROL.DATASET_HEALTH_V`. The enterprise dashboard layer is not a runtime dependency for domain pipelines.

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

The same non-destructive rule applies to project-level control-plane files created by `init-project`: existing files are never overwritten on rerun.

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

Source manifests do not define connector offsets or hidden runtime SQL generation.

## Slim Silver pipeline metadata

RAW contracts own evidence semantics such as business key, ordering columns, idempotency key, source timestamp and delete semantics. Silver pipeline metadata does not repeat those values.

The framework uses RAW evidence at scaffold/validation time and keeps production transformation implementation explicit in committed SQL.

## SCD2 default

The default SCD2 physical model is one history table containing all historical versions. Current-state access is the active-row predicate, normally:

```sql
WHERE IS_ACTIVE = TRUE
```

A stable current view can be exposed for convenience. A separately materialized current table is optional and should be justified by project performance needs.

Dataset implementations can evolve through active/candidate versions. Candidate versions are built and validated in parallel before lightweight cutover; consumers continue to use stable published Silver names.

## SLA, health and repair

Each logical dataset can have stage-specific SLA policy covering Source -> Bronze, Bronze -> Silver, Silver -> Gold and end-to-end freshness. Latency and freshness are separate metrics, and cadence can be continuous, interval-based or scheduled-deadline.

Domain run ledgers feed `CONTROL.DATASET_HEALTH` and dashboard-ready views. Repair follows the latest-known-good-layer rule:

```text
Gold wrong / Silver correct   -> rebuild dbt descendants
Silver wrong / Bronze correct -> candidate version + replay
Bronze wrong                  -> repair ingestion, then replay downstream
```

Replay, backfill and reset are separate operations. The first repair automation direction is to generate explicit reviewable SQL/scripts for engineers to execute, not an autonomous production repair engine.

## dbt and deployment

Silver processing and dbt stay in the same domain repository so one Git SHA represents one domain release. `init-project` creates only a dbt skeleton (`models/sources`, `models/marts`, `models/semantic`, `tests`); it does not generate marts, KPIs, or semantic business logic.

A domain repository owns two committed manifests when it adopts the control plane:

```text
control_plane/deploy_manifest.txt
silver_processing/deploy_manifest.txt
```

The reusable deployment workflow validates contracts, applies committed domain control-plane SQL first, then committed Silver SQL, then runs dbt for Gold/Semantic. Existing repositories without a control-plane manifest are migrated gradually and are not forced into deployment-time scaffolding.

## Deliberately absent

The toolkit does not contain a universal source-discovery engine, universal ingestion orchestrator, central generic SCD runtime engine, runtime metadata routing, metadata-to-runtime transformation SQL generation, deployment-time scaffolding, automatic business Mart/KPI/semantic generation, or connector-state engines for technologies that already own their checkpoint state.

Domain-local control procedures are allowed for operational concerns such as health/SLA evaluation, incident lifecycle, run logging and version state management. Those procedures must not become hidden business transformation engines.

Live Snowflake/WIF acceptance remains a separate integration stage until a configured DEV environment is available.
