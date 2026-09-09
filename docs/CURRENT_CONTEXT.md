# Current Context — Enterprise Snowflake Data Project Toolkit

Updated: 2026-09-09

## Canonical direction

```text
Framework owns project creation.
Domain repositories own project evolution.
```

The Framework is a Python project toolkit, not a runtime abstraction. The canonical data boundary is:

```text
Source -> Ingestion -> BRONZE
BRONZE -> explicit domain-owned Snowflake SQL -> SILVER
SILVER -> dbt -> GOLD -> SEMANTIC
```

Source system is the long-lived organization boundary across `config/sources`, `contracts/raw`, `ingestion`, and `silver_processing`.

## Ownership guardrail

Scaffolding is append-only at dataset-directory level. Once `silver_processing/<source>/<dataset>/` exists, it belongs to the domain repository forever. `esf scaffold` and `esf scaffold-all` never overwrite or repair it, and there is no `--force` escape hatch.

## Retained reusable capabilities

- project/source/RAW/Silver contract validation;
- `esf init-project` and `esf add-source`;
- read-only `esf plan`;
- one-time `esf scaffold` / `esf scaffold-all`;
- workspace/query-tag utilities;
- reusable CI/deployment workflows;
- reference patterns and static tests.

## Removed runtime concepts

There is no shared dbt package, custom SCD materialization, metadata runtime routing, connector state, central SCD runtime engine, or deployment-time SQL generation.

## Deployment model

Domain repositories commit an ordered `silver_processing/deploy_manifest.txt`. The reusable workflow validates the project, executes those committed SQL files in order, then runs ordinary dbt from trusted Silver into Gold/Semantic.

## Proof boundary

Repository/static CI does not equal live Snowflake proof. DEV WIF, actual Snowflake execution, cross-domain denial, live SCD scenarios and promotion still require a configured live-acceptance gate.
