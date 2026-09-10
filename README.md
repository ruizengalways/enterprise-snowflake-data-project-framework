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
├── contracts/
│   ├── drafts/
│   └── raw/
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

## RAW contract authoring gate

RAW contracts are reviewed engineering declarations, not discovery output. The Framework does not infer business keys, timestamps, ordering, CDC/delete semantics, capture fidelity or SCD pattern.

Incomplete work stays outside the production contract boundary:

```text
contracts/drafts/<source>/<dataset>.yml
```

Only finalized contracts live under:

```text
contracts/raw/<source>/<dataset>.yml
```

Typical flow:

```bash
esf add-source fleet_mssql --project-root .
esf raw-contract-draft customer --source fleet_mssql --project-root .
# Edit contracts/drafts/fleet_mssql/customer.yml and resolve every TODO.
esf raw-contract-finalize customer --source fleet_mssql --project-root .
esf add-dataset customer --source fleet_mssql --pattern scd2 --project-root .
esf plan --source fleet_mssql --project-root .
esf scaffold-preview customer --source fleet_mssql --project-root .
esf scaffold scd2 customer --source fleet_mssql --project-root .
```

`raw-contract-draft` creates a draft once and never overwrites it. `raw-contract-finalize` refuses unresolved TODO values, runs the canonical RAW schema/semantic validation, then moves the exact reviewed bytes into `contracts/raw/`. It does not add the dataset to the source manifest and never overwrites an existing formal contract. See `docs/architecture/RAW_CONTRACT_AUTHORING.md`.

## Domain-local control plane

Each domain owns its own `CONTROL` schema. Do not put all domains into one shared writable control database.

A fresh project contains committed control-plane migrations through:

```text
001_objects.sql
010_observability_views.sql
020_refresh_health.sql
030_sla_incident_lifecycle.sql
040_health_task.sql
050_dataset_lifecycle_status.sql
060_run_evidence_api.sql
070_enterprise_health_export.sql
080_data_quality_reconciliation.sql
```

The model includes dataset/version identity, SLA/lifecycle state, ingestion/pipeline/dbt run evidence, DQ/reconciliation evidence, dataset health, incidents, repair audit and version validation.

Operational evidence follows one domain contract:

```text
source-specific ingestion -> CONTROL.INGESTION_RUN
Silver apply procedure    -> CONTROL.PIPELINE_RUN
Silver validation         -> CONTROL.DQ_RESULT
dbt model result          -> CONTROL.DBT_RUN
reconciliation code       -> CONTROL.RECONCILIATION_RESULT
```

The ingestion ledger API records evidence only; it does not replace connector runtimes or own offsets/checkpoints. New dbt projects include an `on-run-end` macro. Per-dataset Gold health is opt-in with `config.meta.esf_dataset_id` so cross-dataset business marts are not falsely assigned to one source dataset.

## Data quality and reconciliation

Run success and freshness are not enough to prove that published data is structurally acceptable. The Framework therefore standardizes **quality evidence**, not a central rule engine.

For standard Silver patterns, generated `020_validate.sql` is a version-local stored procedure. A normal generated task executes:

```text
CALL dataset APPLY procedure
CALL dataset VALIDATE procedure
```

The starter checks are intentionally narrow:

```text
append       -> duplicate idempotency key + NULL business key
scd1         -> duplicate business key + NULL business key
full_refresh -> duplicate business key + NULL business key
scd2         -> multiple active rows + NULL business key + overlapping effective periods
custom       -> domain-authored
```

After scaffold, those checks are ordinary domain-owned SQL. Business DQ rules are not stored as executable metadata in CONTROL.

Reconciliation is even more conservative: the Framework does not assume row-count equality or infer what two boundaries should compare. Domain/source-specific code computes a valid comparison and may write normalized evidence through `CONTROL.RECORD_RECONCILIATION_RESULT`.

Evidence is fail-closed. Intended status is `PASS`/`FAIL`; unknown values become `INVALID` and count as failures. Intended severity is `ERROR`/`WARN`; unknown severity is treated as `ERROR`.

Production DQ health uses only the active implementation version. Candidate evidence remains available for shadow/release review without poisoning a healthy active version. For the same reconciliation stage, active-version evidence takes precedence over unversioned evidence; versionless evidence remains appropriate for boundaries such as Source -> Bronze.

`ERROR` failures contribute RED health and can maintain `DQ_FAILURE` / `RECONCILIATION_FAILURE` incidents. `WARN` failures contribute YELLOW without opening an automatic failure incident. The quality-incident task is serverless and created suspended. See `docs/architecture/DATA_QUALITY_RECONCILIATION.md` and the generated `operations/reconciliation/README.md`.

## Enterprise health export

Cross-domain health uses `CONTROL.ENTERPRISE_HEALTH_EXPORT_V` and `CONTROL.DOMAIN_HEALTH_SUMMARY_V`. Enterprise monitoring explicitly aggregates those read-only contracts; health calculation and writable state remain inside each domain.

After migration 080 the export carries `DQ_STATUS`, `RECONCILIATION_STATUS`, `LAST_DQ_AT` and `LAST_RECONCILIATION_AT` in addition to lifecycle, stage, SLA, latency, freshness and incident fields.

Because migration 080 extends the export contract, participating domains should be upgraded coherently before changing a central `SELECT * UNION ALL` view. During staggered upgrades, select the explicit shared column set centrally.

## CLI

```bash
python -m pip install .

esf init-project --project-root .
esf control-plan --project-root .
esf add-source fleet_mssql --project-root .
esf raw-contract-draft customer --source fleet_mssql --project-root .
esf raw-contract-finalize customer --source fleet_mssql --project-root .
esf add-dataset customer --source fleet_mssql --pattern scd2 --project-root .
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
  --source fleet_mssql --action pause --version v1 --project-root .

esf lifecycle-sql customer decommission_2026q4 \
  --source fleet_mssql --action decommission --project-root .

esf repair-plan customer --source fleet_mssql --problem silver --project-root .
esf repair-sql customer v2 --source fleet_mssql --project-root .
esf release-sql customer --source fleet_mssql --from-version v1 --to-version v2 --project-root .
esf validate --project-root .
```

`add-dataset` performs one narrow write: it appends a missing dataset declaration to one source manifest. It defaults the RAW path to `contracts/raw/<source>/<dataset>.yml`, requires that reviewed contract to exist under the same source, preserves existing YAML comments/order through round-trip editing, does not modify existing dataset declarations and does not scaffold SQL.

There is deliberately **no `--force`**.

## Ownership rule

```text
NOT EXISTS
    -> create/append the requested ownership unit
EXISTS
    -> DOMAIN OWNED FOREVER
```

A RAW draft is created once. A finalized RAW contract is never overwritten by finalization. Once a source-manifest dataset declaration exists, `add-dataset` never changes it. Once `silver_processing/<source>/<dataset>/` exists, normal scaffold commands change zero bytes inside it. A candidate version is a separate ownership unit under `versions/vN/`. Generated SLA/lifecycle/repair/release operation directories use the same rule.

Project initialization is also append-only. A Framework upgrade may introduce a new control migration, macro, example or runbook, but rerunning `init-project` never rewrites existing project files or the domain-owned `control_plane/deploy_manifest.txt`. `esf control-plan` reports explicit upgrade gaps.

## New dataset implementation layout

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

Generated code is intended to be read and changed by domain engineers.

## Standard Silver patterns

The Framework scaffolds `append`, `full_refresh`, `scd1`, `scd2` and `custom`.

For standard patterns, the generated implementation owns its physical objects, apply procedure, replay procedure, validation procedure and Task/readiness source where appropriate. Pattern reuse happens at scaffold time; there is no central metadata-driven SCD runtime.

SCD2 keeps complete history in one physical history table. Current state is `WHERE IS_ACTIVE = TRUE`. Stable published Silver views hide V1/V2 implementation details.

## Versioning and blue/green

```text
v1 ACTIVE
  -> scaffold-version v2
  -> deploy candidate
  -> full bootstrap / replay
  -> catch up
  -> shadow
  -> validate + compare
  -> review candidate DQ evidence
  -> release-sql
  -> engineer reviews activate.sql / rollback.sql
```

`release-sql` generates files only. It does not perform cutover or automatically approve a candidate.

## SLA, health and incidents

SLA belongs to the logical dataset, not to the source manifest or implementation version. Supported cadence models are `CONTINUOUS`, `INTERVAL` and `SCHEDULED_DEADLINE`. Latency and freshness are separate metrics.

`CONTROL.EVALUATE_DOMAIN_HEALTH()` refreshes base timing/SLA health and manages ingestion/pipeline/dbt/SLA incidents. `CONTROL.EVALUATE_QUALITY_INCIDENTS()` manages DQ/reconciliation failure incidents. Logical dataset lifecycle is explicit: `ACTIVE`, `PAUSED`, `DECOMMISSIONED`.

## Repair

Repair starts from the latest known-good layer:

```text
Gold wrong / Silver correct   -> rebuild dbt descendants
Silver wrong / Bronze correct -> candidate version + replay
Bronze wrong                  -> repair ingestion, then replay downstream
```

`repair-plan` is read-only. `repair-sql` generates reviewable candidate-only repair scripts for the four standard patterns:

```text
append       -> idempotent Bronze event replay
scd1         -> ordered current-state rebuild/merge
scd2         -> affected-key history rebuild
full_refresh -> complete Bronze snapshot rebuild
custom       -> domain-authored repair
```

A newly created candidate should normally receive a full bootstrap with no `--from`/`--to`. Bounded replay assumes a known-correct candidate baseline outside the requested window. Full-refresh deliberately rejects time ranges.

DQ/reconciliation can identify a failing layer or boundary, but the Framework does not automatically execute repair. Active production is not overwritten by generated repair scripts. Release SQL remains a separate explicit step after validation.

## Dataset/domain lifecycle

`esf lifecycle-sql` generates pause/resume/soft-decommission SQL and never executes it. Soft decommission preserves Bronze/Silver data, published views and audit evidence. Physical cleanup happens later in a separately approved retention/governance change. New projects include `docs/DOMAIN_DECOMMISSION.md`.

## dbt and deployment

Silver processing and dbt remain in the same domain repo so one Git SHA identifies one domain release. dbt starts from trusted Silver. Mart/KPI/Semantic remain exploratory domain work; the Framework provides skeletons/examples rather than automatic business logic generation.

The reusable deployment workflow executes committed control-plane SQL first, then committed Silver SQL, then dbt. Scaffolding never occurs during deployment.

## Deliberately absent

The toolkit does not contain a universal source-discovery engine, universal source-profiling engine, universal ingestion orchestrator, central generic SCD runtime engine, runtime metadata routing, metadata-to-runtime transformation SQL generation, deployment-time scaffolding, connector offset/checkpoint ownership, generic executable DQ-rule metadata, automatic reconciliation-rule inference, automatic business-key/SCD/SLA inference, one-click destructive decommission, or automatic business Mart/KPI/Semantic generation.

Live Snowflake/WIF acceptance remains a separate integration gate until a configured DEV Snowflake environment is available.
