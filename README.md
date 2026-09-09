# Enterprise Snowflake Data Project Toolkit

This repository is intentionally **not a data runtime framework**.

Its job is to make domain repositories easy to start, validate, review and operate without hiding SQL behind shared Jinja/macros.

## Architecture boundary

```text
Source
  -> ingestion
  -> BRONZE                 raw / replayable evidence
  -> explicit Silver SQL    domain-owned Snowflake SQL
  -> SILVER                 trusted current/history/canonical data
  -> dbt
  -> GOLD                   marts / dimensions / facts / KPI
  -> SEMANTIC               consumption-facing models
```

`Source -> BRONZE` is ingestion responsibility. Connector positions such as SQL Server LSNs, Kafka offsets and API cursors remain with the ingestion technology.

`BRONZE -> SILVER` is explicit Snowflake processing. SCD1, SCD2, deduplication, delete handling, replay and late-arrival correction live in readable SQL committed to the domain repository.

**dbt starts from trusted Silver.** It is used for the warehouse modeling work it is good at: facts, dimensions, marts, business joins, aggregations, tests, lineage, documentation and semantic models.

## What is reusable

The toolkit centralizes only things that remain useful without hiding runtime behavior:

- packaged JSON Schemas for project, RAW and Silver pipeline contracts;
- `esf validate` for static contract checks;
- `esf scaffold` for copying reference patterns into a domain repository;
- reusable CI/deployment workflows;
- human-readable reference patterns and tests.

Generated Silver SQL belongs to the domain team. It is committed, reviewed and modified in that repository. A later toolkit release does not silently change an already-deployed pipeline.

## What is deliberately not reusable runtime

There is no shared dbt package, no `esf_apply_dataset_config`, no custom dbt SCD materialization and no metadata-to-SQL runtime engine.

A domain engineer should be able to understand a Silver pipeline by opening:

```text
silver_processing/<dataset>/
  README.md
  pipeline.yml
  001_objects.sql
  010_apply.sql
  020_validate.sql
```

without reading this repository first.

## CLI

```bash
python -m pip install .

esf validate --project-root ../enterprise-snowflake-transport-analytics

esf scaffold scd2 vehicle_status \
  --project-root ../enterprise-snowflake-transport-analytics \
  --raw-contract contracts/raw/vehicle_status.yml
```

`scaffold` creates source files once. It does not participate when the pipeline runs.

## Reuse model

The initial scaffold patterns are `append`, `full_refresh`, `scd1` and `scd2`; `custom` is accepted by the Silver contract for domain-owned implementations that do not fit a standard starter.

The SCD2 pattern preserves deterministic source ordering, idempotency, tombstone delete/reinsert semantics, authoritative history and affected-key late-arrival rebuild. The concrete SQL remains visible in the domain repository.

## Deployment

A domain repository commits `silver_processing/deploy_manifest.txt`. The reusable workflow validates the contracts, applies exactly those committed SQL files in order, and then runs ordinary dbt from Silver into Gold/Semantic. It does not generate Silver SQL at deploy time.

## Control plane

`PLATFORM_CONTROL` remains a separate enterprise concern for run/reset lifecycle, audit, quality and guarded domain-scoped operational APIs. Domain processing SQL may call those explicit APIs; it never receives direct DML on shared control tables.

## Portability

Domain standalone fixtures remain independent of this toolkit, `PLATFORM_CONTROL`, Terraform and enterprise WIF.
