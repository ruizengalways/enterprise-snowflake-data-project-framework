# Enterprise Snowflake Data Project Framework

Versioned golden path for Snowflake data-project repositories.

## Purpose

Implement reusable technical behaviour once so Health, Transport and future domains do not copy/paste or independently reimplement platform mechanics.

Shared mechanics belong here when a bug fix would otherwise require coordinated edits across every project repo. Business joins, calculations, source predicates and domain rules remain explicit project SQL/code.

## Current executable baseline

```text
src/enterprise_snowflake_framework/
├── workspaces.py
├── query_tags.py
├── metadata_validation.py
├── targets.py
└── dbt_vars.py

project_schema/
├── project.schema.json
├── dataset.schema.json
└── raw_contract.schema.json

validation/validate_metadata.py
scripts/
├── render_workspace_sql.py
├── render_query_tag.py
├── resolve_dbt_target.py
├── render_dbt_vars.py
└── assert_dbt_manifest.py

dbt_package/
├── dbt_project.yml
└── macros/
    ├── environment/targets.sql
    └── loading/strategies.sql

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

The renderer validates identifiers and produces guarded create/drop SQL. PR schemas are transient with zero-day Time Travel and cleanup is prefix-guarded.

Platform Infra owns stable permissions/roles/warehouses; this framework owns workspace naming/rendering mechanics.

## Query tags

Canonical compact JSON `QUERY_TAG` fields:

```text
required: project, environment, workload
optional: source, pipeline, dataset, run_id, git_sha, pr_number, operation
```

The builder rejects unsupported keys, fails before Snowflake's 2000-character limit, and can render `ALTER SESSION SET QUERY_TAG` SQL. Do not put personal, secret, regulated or business-payload data in query tags.

## Project metadata contracts

Version 1 schemas cover project identity, dataset technical behavior and project-owned RAW contracts.

Dataset metadata includes:

```text
raw_contract
load_strategy
implementation
business_key
watermark_column
freshness
reconciliation
```

RAW contracts include source/entity/grain/business key, columns/types/nullability/classification, source timestamp, snapshot/append/CDC semantics, cadence, retention and breaking-change policy.

The validator adds bounded cross-file checks. It intentionally does **not** encode business joins, formulas, arbitrary SQL or workflow branching in YAML.

Reusable validation action:

```text
.github/actions/validate-metadata/action.yml
```

## dbt physical target resolution

Current stable reference versions:

```text
dbt-core      1.12.3
dbt-snowflake 1.12.0
```

The target resolver derives physical database, warehouse and schema prefix from project/environment/workload inputs.

```text
DEV personal -> DEV_<DOMAIN> / WH_<DOMAIN>_TRANSFORM / <DEVELOPER>_<LAYER>
PR CI        -> CI_<DOMAIN>  / WH_<DOMAIN>_CI        / PR_<NUMBER>_<LAYER>
UAT          -> UAT_<DOMAIN> / stable layer schemas
PROD         -> PROD_<DOMAIN>/ stable layer schemas
```

Domain root projects keep explicit wrapper macros delegating database/schema naming to the framework dbt package. Model SQL should use `ref()` / `source()` and should not hard-code physical environment databases.

Machine profiles use Snowflake `workload_identity` + OIDC + a short-lived token; no password/private key belongs in the project profile.

See platform ADR-029.

## Metadata-to-dbt bridge

`render_dbt_vars.py` validates a project tree first and exposes only bounded technical metadata as:

```text
esf_project
esf_datasets
```

The reusable `dbt-static-check` action renders those vars and supplies them to offline `dbt parse`. Therefore metadata changes that affect dbt materialization are validated together with the project package/profile/macros.

## Basic standard load strategies

A standard model can identify its governed dataset:

```jinja
{{ enterprise_snowflake_framework.esf_configure_dataset('vehicle_position') }}
```

The model query remains explicit SQL. The framework reads `esf_datasets` metadata and currently maps:

```text
full_refresh
  -> materialized=table

append_only
  -> materialized=incremental
  -> incremental_strategy=append

incremental_merge
  -> materialized=incremental
  -> incremental_strategy=merge
  -> unique_key derived from dataset.business_key
```

Important boundary: `append_only` does **not** invent the dataset/source checkpoint predicate. The rows selected by the model during an incremental invocation are the rows appended. Source/watermark filtering remains explicit until a separately approved generic checkpoint primitive exists.

The basic macro deliberately rejects:

```text
implementation: custom
scd2_snapshot
scd2_merge
scd2_stream_task
```

Custom implementations stay explicit project code. SCD2 strategies require dedicated framework implementations and invariant tests; they never silently degrade to a basic incremental model.

See platform ADR-030.

## CI proof

Framework CI currently proves:

- workspace/query-tag/metadata/target/dbt-vars Python tests;
- minimal metadata validation and dbt-vars rendering;
- pinned dbt installation;
- target resolution through `dbt deps` + offline `dbt parse`;
- manifest target `CI_HEALTH.PR_123_STAGING`;
- `full_refresh -> table`;
- `append_only -> incremental + append`;
- `incremental_merge -> incremental + merge + metadata-derived unique_key`.

This is configuration-level proof. Live Snowflake execution/idempotency/performance/recovery tests remain pending real DEV infrastructure.

## Reusable PR workspace workflow

`.github/workflows/pr-workspace.yml` creates/drops guarded `PR_<n>_*` schemas through the domain CI service identity. It requests an account-scoped GitHub OIDC token and currently runs only framework-generated workspace SQL, not arbitrary PR business code with Snowflake credentials.

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

## Consumption model

Projects consume immutable framework revisions and upgrade deliberately. They do not copy shared implementation and do not follow framework `main` implicitly.

Health and Transport currently use one aligned pinned framework revision across metadata validation, dbt package/static validation and PR workspace orchestration.

## Next framework growth

```text
query-tag integration with dbt invocation/model lifecycle
reconciliation/freshness/audit primitives
dedicated SCD2 snapshot/merge/stream-task implementations + invariants
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
