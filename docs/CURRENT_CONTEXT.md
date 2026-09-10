# Current context

## Framework position

This repository is a project-creation and operations toolkit for readable Enterprise Snowflake domain repositories. It is not a universal data runtime.

The framework owns safe project/source scaffolding, RAW/Silver contract validation, explicit pattern source-code generation, domain-local control-plane foundations and reusable CI/deployment workflows. Existing ownership units are never overwritten by scaffolding.

## Domain boundary

One business domain is one domain repository and normally one domain Snowflake database per environment.

```text
enterprise-snowflake-transport-analytics
  -> DEV_TRANSPORT / UAT_TRANSPORT / PROD_TRANSPORT
```

A domain may contain many sources. Source boundaries are preserved in repository paths and new Snowflake object names. Existing domain-owned pipelines are never renamed automatically.

## Ingestion

`ingestion/` is a source-specific integration boundary. Projects may use Openflow, Snowpipe, Kafka connectors, external ETL/orchestrators or project-specific API ingestion. The Framework does not implement a universal ingestion runtime or own mature connector checkpoints.

Control migration 060 provides optional BEGIN/COMPLETE/FAIL ingestion run-evidence procedures. They write `CONTROL.INGESTION_RUN`; they do not schedule or route ingestion.

## Bronze -> Silver

Preferred Snowflake-native shape:

```text
BRONZE -> Stream/readiness -> Task -> dataset-local SQL procedure -> SILVER
```

Standard patterns are append, full_refresh, scd1, scd2 and custom. Pattern algorithms are reused at scaffold time to generate explicit dataset-local source code. There is no central metadata-driven SCD runtime.

New dataset starters include explicit object/apply/replay/validation/task/register/publish SQL plus policy and deploy-manifest fragments. Generated standard apply procedures write RUNNING/SUCCESS/FAILED evidence to `CONTROL.PIPELINE_RUN`.

## Domain-local control plane

Each domain owns its own `CONTROL` schema. Do not create one shared writable `PLATFORM_CONTROL` database across all domains.

The control plane includes dataset/version identity, lifecycle, SLA policy, ingestion/pipeline/dbt run evidence, health, incidents, version validation and repair audit. Enterprise health dashboards may union stable read-only health views from each domain.

Logical dataset lifecycle is explicit: `ACTIVE`, `PAUSED`, `DECOMMISSIONED`.

Control-plane upgrades remain explicit. Rerunning `init-project` creates newly introduced missing files without overwriting existing files or the domain-owned deploy manifest. `esf control-plan` reports repo/manifest gaps.

## Run evidence

```text
source-specific ingestion -> CONTROL.INGESTION_RUN
Silver apply procedure    -> CONTROL.PIPELINE_RUN
dbt model result          -> CONTROL.DBT_RUN
```

New dbt projects include an `on-run-end` macro. A model only participates in one logical dataset's Gold health when it explicitly declares `config.meta.esf_dataset_id`; cross-dataset business marts should normally remain unmapped. Existing domain repos are not silently opted into dbt logging because `init-project` never rewrites an existing `dbt_project.yml`.

## SCD2 default

The default SCD2 model is one physical history table per implementation version. Current state is `IS_ACTIVE = TRUE`, exposed through a version-local current view and stable published current view. A separate physical current table is optional when performance evidence justifies it.

## Versioning and blue/green

Candidate versions live under `silver_processing/<source>/<dataset>/versions/vN/` and own independent physical objects, Stream/Task where appropriate, apply/replay procedures and validation SQL. Creating v2 changes zero bytes in v1.

```text
scaffold -> deploy -> bootstrap/replay -> catch up -> shadow -> validate -> compare -> release SQL -> explicit cutover
```

`release-sql` generates activate/rollback SQL for review. `esf` never executes it.

## SLA and observability

SLA belongs to the logical dataset, not to the source manifest or implementation version. Supported cadence types are `CONTINUOUS`, `INTERVAL` and `SCHEDULED_DEADLINE`. Latency and freshness are separate metrics. Stage policy can cover Source -> Bronze, Bronze -> Silver, Silver -> Gold and end-to-end freshness.

`CONTROL.EVALUATE_DOMAIN_HEALTH()` refreshes health and automatic ingestion/pipeline/dbt/SLA incidents. A sustained condition reuses one incident key; recovery resolves it. The domain health task is serverless and created suspended.

## Dataset lifecycle

`esf lifecycle-sql` generates explicit pause/resume/soft-decommission SQL and never executes it. Pause/resume require an explicit implementation version. Soft decommission stops known implementation tasks, marks the logical dataset `DECOMMISSIONED`, retires versions and preserves Bronze/Silver/published/audit evidence. Physical cleanup is a separate approved retention/governance change.

## Repair

Repair starts from the latest known-good layer:

- Gold wrong / Silver correct -> rebuild dbt descendants.
- Silver wrong / Bronze correct -> build a candidate and replay Bronze.
- Bronze wrong -> repair ingestion first, then replay downstream.

Replay, backfill and reset remain distinct.

`repair-plan` is read-only. `repair-sql` generates candidate-only reviewable scripts for the four standard patterns:

```text
append       -> idempotent Bronze event replay
scd1         -> ordered current-state rebuild/merge
scd2         -> affected-key history rebuild
full_refresh -> complete current Bronze snapshot rebuild
custom       -> domain-authored
```

A new empty candidate should normally use a full bootstrap with no range bounds. Bounded replay assumes a correct candidate baseline outside the requested range. Full-refresh rejects time ranges. All standard replay procedures write `CONTROL.REPAIR_RUN` evidence. Active production is not changed until a separately generated and reviewed release.

## Gold / KPI / Semantic

These remain exploratory domain work. The Framework keeps skeletons/examples but does not auto-generate business marts, KPI SQL or semantic business models.

## Architectural guardrails

Continue to reject deployment-time scaffolding, runtime metadata routing, metadata -> runtime transformation SQL generation, central generic SCD runtime engines, universal ingestion orchestration, connector offset/checkpoint ownership, hidden active-version switching, automatic production repair execution, automatic SLA threshold inference, destructive one-click decommission and automatic business Mart/KPI/Semantic generation.

The control plane may centralize operational health/version/incident/lifecycle/run-evidence logic inside a domain, but must not hide dataset transformation behavior.
