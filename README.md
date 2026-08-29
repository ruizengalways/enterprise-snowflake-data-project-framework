# Enterprise Snowflake Data Project Framework

Versioned golden path for Snowflake data-project repositories.

## Purpose

Implement reusable technical behaviour once so Health, Transport and future domains do not copy/paste or independently reimplement platform mechanics.

Shared mechanics belong here when a bug fix would otherwise require coordinated edits across every project repo. Business joins/calculations/domain rules remain explicit project SQL/code.

## Current executable baseline

```text
src/enterprise_snowflake_framework/
├── workspaces.py
├── query_tags.py
└── metadata_validation.py

project_schema/
├── project.schema.json
├── dataset.schema.json
└── raw_contract.schema.json

validation/validate_metadata.py
scripts/render_workspace_sql.py
scripts/render_query_tag.py
tests/
examples/minimal-project/
.github/workflows/framework-ci.yml
```

### Workspace lifecycle

```text
personal DEV: <DEVELOPER>_<LAYER>
PR CI:        PR_<NUMBER>_<LAYER>
```

The renderer validates unquoted Snowflake identifiers and produces guarded create/drop SQL. PR schemas are transient with zero-day Time Travel and cleanup is prefix-guarded.

Platform Infra owns stable permissions/roles/warehouses; this framework owns workspace naming/rendering mechanics.

### Query tags

Canonical compact JSON `QUERY_TAG` fields:

```text
required: project, environment, workload
optional: source, pipeline, dataset, run_id, git_sha, pr_number, operation
```

The builder rejects unsupported keys, fails before Snowflake's 2000-character limit, and can render `ALTER SESSION SET QUERY_TAG` SQL. Do not put personal, secret, regulated or business-payload data in query tags.

### Project metadata contracts

Version 1 JSON Schemas now exist for:

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

The validator combines JSON Schema validation with deliberately narrow technical checks such as contract references, duplicate columns, CDC operation/sequence columns, keyed-strategy business keys and freshness threshold ordering.

It intentionally does **not** encode business joins, formulas, arbitrary SQL or workflow branching in YAML.

Run against a project tree:

```bash
python -m pip install -e .
python validation/validate_metadata.py --project-root examples/minimal-project
```

See ADR-028 in `enterprise-snowflake-platform-infra`.

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

## CI

`.github/workflows/framework-ci.yml` currently:

- installs the framework and validation dependencies;
- runs workspace/query-tag/metadata unit tests;
- validates the checked-in minimal project example;
- smoke-tests PR workspace SQL rendering;
- smoke-tests QUERY_TAG SQL rendering.

The current metadata implementation depends only on `PyYAML` and `jsonschema` in addition to Python's standard library.

## Future growth

Next layers should add:

```text
dbt environment/database/schema resolution
reusable PR workspace workflow
approved load/SCD2 macros
reconciliation/freshness/audit primitives
DEV -> PR CI -> UAT -> PROD reusable delivery workflows
rollback/recovery/backfill templates
```

Do not add domain business logic here.

## Consumption model

Projects consume released/pinned framework versions and upgrade deliberately; they do not permanently copy shared implementation into each repo.

Canonical architecture/status are maintained in:

```text
enterprise-snowflake-platform-infra/docs/CURRENT_CONTEXT.md
enterprise-snowflake-platform-infra/docs/PROJECT_BLUEPRINT.md
```
