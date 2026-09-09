# Current Context — Silver-first Toolkit

Updated: 2026-09-09

## Canonical direction

The Framework is being simplified from a dbt runtime abstraction into a project toolkit.

```text
Source -> ingestion -> BRONZE
BRONZE -> explicit domain-owned Snowflake SQL -> SILVER
SILVER -> dbt -> GOLD -> SEMANTIC
```

The design priority is local readability: a domain engineer should not need to open this repository to understand how a production SCD pipeline behaves.

## Removed runtime concepts

The current simplification removes the shared dbt package, `esf_apply_dataset_config`, custom SCD1/SCD2 dbt materializations, dataset materialization/runtime routing, dbt vars rendering and the mixed-strategy dbt runtime example.

## Retained reusable capabilities

- project/RAW/Silver contract validation;
- one-time pattern scaffolding;
- workspace/query-tag utilities;
- reusable CI/deployment workflows;
- reference patterns and static checks.

## Deployment model

Domain repositories commit an ordered `silver_processing/deploy_manifest.txt`. The reusable deployment workflow validates the project, executes those committed SQL files in order, then runs ordinary dbt from trusted Silver into Gold/Semantic.

## Platform boundary

`PLATFORM_CONTROL` remains separate and guarded. Connector-specific positions remain outside this toolkit. Processing reset preserves Bronze evidence and rebuilds reconstructable processing outputs.

## Proof boundary

Repository/static implementation does not equal live Snowflake proof. DEV WIF, actual Snowflake execution, cross-domain denial, live SCD scenarios and promotion still require the platform live-acceptance gate.
