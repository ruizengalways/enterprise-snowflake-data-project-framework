# Enterprise Snowflake Data Project Framework

Versioned golden path for Snowflake data-project repositories.

## Purpose

Provide reusable technical behaviour once so Health, Transport and future projects do not copy/paste or independently reimplement the same engineering mechanics.

## This repository owns

- versioned dbt package and reusable macros
- generic tests
- approved load-strategy implementations
- SCD2 mechanics
- reconciliation and freshness framework
- audit and operational metadata contracts
- project/dataset metadata schemas and validation
- reusable GitHub Actions workflows
- rollback, recovery and backfill workflow templates
- project bootstrap/template capability
- personal DEV / PR CI workspace lifecycle helpers
- canonical Snowflake query-tag metadata helpers

## This repository does not own

- Health or Transport business rules
- project-specific RAW contracts
- source-system simulation
- central Snowflake account/RBAC/warehouse infrastructure
- environment-specific project business configuration
- employee identity lifecycle

## Design rule

If fixing a shared technical behaviour would otherwise require manual edits in every data project, that behaviour probably belongs here.

Use metadata for stable technical behaviour and explicit SQL/code for genuine domain logic. Support `implementation: custom` without exempting custom implementations from standard testing, observability, reconciliation, audit and recovery.

## First executable slice

The framework now contains dependency-free Python utilities for two cross-project concerns.

### Workspace lifecycle

```text
personal DEV: <DEVELOPER>_<LAYER>
PR CI:        PR_<NUMBER>_<LAYER>
```

`scripts/render_workspace_sql.py` validates identifiers and renders guarded create/drop SQL. PR schemas are transient with zero-day Time Travel and must be explicitly cleaned up by the PR lifecycle.

Platform Infra owns the corresponding stable Snowflake permissions and machine roles; this framework owns naming/rendering behaviour.

### Query tags

`scripts/render_query_tag.py` creates compact deterministic JSON `QUERY_TAG` metadata using the common fields:

```text
project
environment
workload
source
pipeline
dataset
run_id
git_sha
pr_number
operation
```

Required fields are `project`, `environment`, and `workload`. Personal/sensitive data does not belong in query tags.

See [`docs/patterns/workspaces-and-query-tags.md`](docs/patterns/workspaces-and-query-tags.md).

## Validation

`.github/workflows/framework-ci.yml` runs the standard-library unit tests and smoke-tests both renderers on every push/PR. There are no third-party runtime dependencies in this first slice.

## Consumption model

Projects consume released framework versions as dependencies and upgrade deliberately; they do not permanently copy the framework into each repository.

The canonical platform architecture and handoff context are maintained in:

```text
enterprise-snowflake-platform-infra/docs/CURRENT_CONTEXT.md
enterprise-snowflake-platform-infra/docs/PROJECT_BLUEPRINT.md
```
