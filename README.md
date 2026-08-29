# Enterprise Snowflake Data Project Framework

Versioned golden path for Snowflake data-project repositories.

## Purpose

Implement reusable technical behaviour once so Health, Transport and future domains do not copy/paste or independently reimplement platform mechanics.

Shared mechanics belong here when a bug fix would otherwise require coordinated edits across every project repo. Business joins, calculations and domain rules remain explicit project SQL/code.

## Current executable baseline

```text
src/enterprise_snowflake_framework/
├── workspaces.py
├── query_tags.py
├── metadata_validation.py
└── targets.py

project_schema/
├── project.schema.json
├── dataset.schema.json
└── raw_contract.schema.json

validation/validate_metadata.py
scripts/
├── render_workspace_sql.py
├── render_query_tag.py
├── resolve_dbt_target.py
└── assert_dbt_manifest.py

dbt_package/
├── dbt_project.yml
└── macros/environment/targets.sql

.github/actions/
├── validate-metadata/action.yml
└── dbt-static-check/action.yml

.github/workflows/
├── framework-ci.yml
└── pr-workspace.yml
```

## Workspace lifecycle

```text
personal DEV: <DEVELOPER>_<LAYER>
PR CI:        PR_<NUMBER>_<LAYER>
```

The renderer validates unquoted Snowflake identifiers and produces guarded create/drop SQL. PR schemas are transient with zero-day Time Travel and cleanup is prefix-guarded.

Platform Infra owns stable permissions/roles/warehouses; this framework owns workspace naming/rendering mechanics.

## Query tags

Canonical compact JSON `QUERY_TAG` fields:

```text
required: project, environment, workload
optional: source, pipeline, dataset, run_id, git_sha, pr_number, operation
```

The builder rejects unsupported keys, fails before Snowflake's 2000-character limit, and can render `ALTER SESSION SET QUERY_TAG` SQL. Do not put personal, secret, regulated or business-payload data in query tags.

## Project metadata contracts

Version 1 schemas cover:

```text
project metadata
  -> code/name/repository/owner team

dataset technical metadata
  -> RAW contract reference
  -> load strategy
  -> standard/custom implementation
  -> business key / watermark
  -> freshness / reconciliation

RAW contract metadata
  -> source/entity/grain/business key
  -> columns/types/nullability/classification
  -> source timestamp
  -> snapshot/append/CDC semantics
  -> cadence/retention/breaking-change policy
```

The validator combines JSON Schema validation with narrow technical checks for contract references, duplicate columns/dataset ids, CDC operation/sequence columns, keyed-strategy business keys, declared timestamp/key columns and freshness threshold ordering.

It intentionally does **not** encode business joins, formulas, arbitrary SQL or workflow branching in YAML.

Reusable validation action:

```text
.github/actions/validate-metadata/action.yml
```

A project checks out its own repo, then invokes the framework action pinned to a commit SHA.

## dbt physical target resolution

Current stable reference versions:

```text
dbt-core      1.12.3
dbt-snowflake 1.12.0
```

`resolve_dbt_target.py` / `targets.py` derive environment-specific database, warehouse and schema-prefix values from technical inputs only.

Examples:

```text
HEALTH + dev + transform + developer alice.smith
  -> DEV_HEALTH
  -> WH_HEALTH_TRANSFORM
  -> schema prefix ALICE_SMITH

HEALTH + ci + ci + PR 123
  -> CI_HEALTH
  -> WH_HEALTH_CI
  -> schema prefix PR_123

HEALTH + uat + transform
  -> UAT_HEALTH
  -> WH_HEALTH_TRANSFORM
  -> stable layer schema names
```

The resolver exports:

```text
ESF_PROJECT_CODE
ESF_ENVIRONMENT
ESF_SCHEMA_PREFIX
DBT_DATABASE
DBT_WAREHOUSE
DBT_DEFAULT_SCHEMA
```

The reusable dbt package consumes these values. Domain projects keep explicit root wrapper macros that delegate to:

```text
enterprise_snowflake_framework.esf_generate_database_name
enterprise_snowflake_framework.esf_generate_schema_name
```

This keeps environment logic out of model SQL while avoiding implicit package override behaviour.

Project profiles contain no passwords/private keys. CI WIF uses `authenticator: workload_identity`, `workload_identity_provider: OIDC`, and a short-lived `SNOWFLAKE_TOKEN` minted close to execution.

Reusable offline validation action:

```text
.github/actions/dbt-static-check/action.yml
```

It installs the pinned dbt versions, resolves a CI target, runs `dbt deps` and `dbt parse`, and does not connect to Snowflake.

## Framework CI proof

Framework CI currently validates:

- workspace/query-tag/metadata/target Python tests;
- minimal metadata example;
- workspace and QUERY_TAG renderers;
- target resolver CLI;
- pinned dbt installation;
- local framework dbt package installation;
- offline `dbt parse`;
- manifest assertion proving `CI_HEALTH.PR_123_STAGING` resolution.

This proves configuration/package/macro resolution, not live Snowflake authorization.

## Reusable PR workspace workflow

`.github/workflows/pr-workspace.yml` creates/drops guarded `PR_<n>_*` schemas through the domain CI service identity. It requests an account-scoped GitHub OIDC token and runs only framework-generated workspace SQL; it does not currently execute untrusted PR business code with Snowflake credentials.

## Approved load-strategy vocabulary

```text
full_refresh
append_only
incremental_merge
scd2_snapshot
scd2_merge
scd2_stream_task
```

Dynamic Tables are not an approved SCD2 mechanism.

`implementation: custom` is a legitimate escape hatch for genuine differences; custom work still participates in contracts, testing, observability, reconciliation, audit and recovery.

## Consumption model

Projects consume immutable framework revisions and upgrade deliberately. They do not copy shared implementation into each repo and do not follow framework `main` implicitly.

Current project repos already consume the metadata validation action, dbt static action, dbt package and PR workspace workflow as thin pinned callers.

## Next framework growth

```text
basic load-strategy primitives and tests
reconciliation/freshness/audit primitives
DEV deployment identity/workflow contract
UAT/PROD promotion identity/workflow contract
rollback/recovery/backfill templates
```

Do not add domain business logic here.

Canonical architecture/status are maintained in:

```text
enterprise-snowflake-platform-infra/docs/CURRENT_CONTEXT.md
enterprise-snowflake-platform-infra/docs/PROJECT_BLUEPRINT.md
```
