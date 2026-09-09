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

A domain may contain many sources. The source boundary is preserved in repository paths and in newly generated Snowflake object names so same-named datasets from different sources cannot collide by default.

Existing domain-owned pipelines are not renamed automatically.

## Ingestion

`ingestion/` is an integration boundary and example area. Projects may use Openflow, Snowpipe, Kafka connectors, external ETL/orchestrators or project-specific API ingestion. The framework does not implement a universal ingestion runtime or mature connector checkpoint engines.

## Bronze -> Silver

This is the framework's primary standardization area.

Preferred Snowflake-native shape:

```text
BRONZE -> Stream/readiness -> Task -> dataset-local SQL procedure -> SILVER
```

Standard patterns remain append, full_refresh, scd1, scd2 and custom. Pattern algorithms are reused at scaffold time to generate explicit dataset-local source code. There is no central metadata-driven SCD runtime.

New dataset starters include `pipeline.yml`, `version.yml`, explicit object/apply/replay/validation/task/register/publish SQL, `060_policy.sql`, and a deploy-manifest fragment.

## Domain-local control plane

Each domain owns its own `CONTROL` schema. Do not create one shared writable `PLATFORM_CONTROL` database across all domains.

The domain control plane includes dataset/version identity, SLA policy, ingestion/pipeline/dbt run evidence, health state, incidents, version validation and repair audit. Enterprise health dashboards may union stable read-only health views from each domain.

Control-plane upgrades remain explicit. Rerunning `init-project` creates newly introduced missing control files without overwriting existing files or the domain-owned deploy manifest. `esf control-plan` reports repo/manifest gaps for review.

## SCD2 default

The default SCD2 model is one physical history table per implementation version. Current state is `IS_ACTIVE = TRUE` and is exposed through a version-local current view plus a stable published current view. A separate physical current table is optional and should be justified by performance evidence.

## Versioning and blue/green

The initial dataset implementation is v1. Candidate versions live under `silver_processing/<source>/<dataset>/versions/vN/` and own independent physical objects, Stream/Task where appropriate, apply/replay procedure and validation SQL. Creating v2 changes zero bytes in v1.

Candidate lifecycle:

```text
scaffold -> deploy -> replay/bootstrap -> catch up -> shadow -> validate -> compare -> release SQL -> explicit cutover
```

`release-sql` generates activate/rollback SQL for review. `esf` never executes those files.

## SLA and observability

SLA belongs to the logical dataset, not to the source manifest and not to an implementation version. Git stores reviewed policy-change SQL; `CONTROL.SLA_POLICY` stores the currently effective policy used by Snowflake health evaluation.

Supported cadence types are `CONTINUOUS`, `INTERVAL` and `SCHEDULED_DEADLINE`. Latency and freshness remain separate metrics. Stage policy can cover Source -> Bronze, Bronze -> Silver, Silver -> Gold and end-to-end freshness.

`CONTROL.SLA_EVALUATION_V` evaluates current policy and `CONTROL.EVALUATE_DOMAIN_HEALTH()` refreshes dataset health plus automatic incident lifecycle. Automatic incidents cover ingestion failure, pipeline failure, dbt failure and SLA violations. A sustained condition reuses one open incident key; recovery resolves it.

`CONTROL.EVALUATE_DOMAIN_HEALTH_TASK` is a domain-local one-minute serverless task. It is created suspended and must be explicitly resumed after validation.

Use `esf sla-sql` to generate a new reviewable policy revision under `operations/sla/`. The command never connects to Snowflake and never overwrites an existing revision file.

## Dataset lifecycle

Use `esf lifecycle-sql` to generate explicit lifecycle SQL. The command never connects to Snowflake and never executes the generated script.

`pause` and `resume` require an explicit version so the Framework never guesses the active implementation from repository state. The generated script changes the explicit Task plus `CONTROL.DATASET.ENABLED`, then refreshes domain health.

`decommission` is intentionally soft: suspend all known implementation Tasks, disable the logical dataset and mark versions retired while preserving published data, Bronze/Silver history and control-plane audit evidence. It does not generate executable DROP statements.

Physical cleanup is a separate approved retention/governance change. New domain repositories include a staged `docs/DOMAIN_DECOMMISSION.md` runbook covering source ingestion shutdown, consumer cutover, retention, infrastructure cleanup and repository archive/removal decisions.

## Repair

Repair begins at the latest correct layer:

- Gold wrong / Silver correct -> rebuild dbt descendants.
- Silver wrong / Bronze correct -> build a candidate version and replay Bronze.
- Bronze wrong -> repair ingestion, then replay downstream layers.

Replay, backfill and reset remain distinct operations. `repair-plan` is read-only. `repair-sql` generates explicit SCD2 candidate replay SQL for engineer review/execution and does not modify active production objects.

## Gold / KPI / Semantic

These remain exploratory domain work. The framework keeps skeletons/examples but does not auto-generate business marts, KPI SQL or semantic business models.

## Architectural guardrails

Continue to reject deployment-time scaffolding, runtime metadata routing, metadata -> runtime transformation SQL generation, central generic SCD runtime engines, universal ingestion orchestration, hidden active-version switching, automatic production repair execution, automatic SLA threshold inference, one-click destructive decommission and automatic business Mart/KPI/Semantic generation.

The control plane may centralize operational health/version/incident/lifecycle logic inside a domain, but must not hide dataset transformation behavior.
