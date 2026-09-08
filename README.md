# Enterprise Snowflake Data Project Framework

Versioned golden path for Snowflake domain/data-product repositories.

## Start here

For a new conversation or implementation session, read:

1. `docs/CURRENT_CONTEXT.md` — active PRs, verified SHAs, blockers, merge order and next gate.
2. `docs/architecture/DATASET_EXECUTION_MODEL.md` — dataset-level strategy/execution model and readable-SQL boundary.
3. `docs/patterns/dataset-control-plane.md` — Git-owned dataset configuration and runtime/control-plane boundary.
4. `docs/patterns/metadata-driven-scd2.md` — standard SCD2 metadata and correctness model.
5. `docs/patterns/bootstrap-handoff.md` — safe initial snapshot -> incremental/CDC handoff.

Human-readable architecture belongs in `docs/`. Machine contracts remain in `project_schema/`, project `config/`, RAW contracts, macros, scripts and tests.

## Responsibility

This repository owns reusable technical behavior that should not be copied independently by Health, Transport or future domain repos. Domain business joins, calculations, source-specific extraction mechanics and genuinely custom logic remain explicit in the domain repository.

The core design rule is:

```text
Metadata = HOW TO RUN
SQL      = WHAT THE DATA MEANS
```

The framework must not turn YAML or Jinja into a replacement business-query language.

## Canonical data-project shape

A domain database uses stable Medallion-aligned schemas:

```text
BRONZE
SILVER_STAGING
SILVER_INTERMEDIATE
SILVER_CANONICAL
GOLD_MARTS
GOLD_SEMANTIC
DQ
```

Personal DEV and PR CI workspaces apply a prefix to the same layer vocabulary:

```text
ALICE_SILVER_STAGING
PR_123_SILVER_STAGING
PR_123_GOLD_MARTS
```

Database placement is environment × domain/data product. Ordinary new physical sources do not require a new database or Terraform-created source schema; source identity stays in Git metadata and object naming unless governance requires an explicit isolation exception.

A database is not a refresh-policy boundary. Every dataset/table independently declares how its target is maintained.

## Dataset metadata v2

Dataset schema v2 separates **target semantics** from **execution mechanism**.

Target semantics:

```text
load.strategy
  full_refresh
  append_only
  incremental_merge
  scd1
  scd2
  custom
```

Execution mechanism:

```text
load.execution.mode
  dbt_batch
  dbt_snapshot
  dynamic_table
  stream_task
  custom
```

This lets a single domain database contain many tables with different requirements without inventing combined names for every implementation variant.

For example:

```text
vehicle_status      scd2              + dbt_batch
vehicle_position    append_only       + dbt_batch
driver              scd1              + dbt_batch
depot_reference     full_refresh      + dbt_batch
current_trip_state  scd1              + dynamic_table
special_vendor_feed custom            + custom
```

See `examples/readable-project/` for a validated mixed-strategy project.

Schema v1 remains supported during migration. Legacy names such as `scd1_merge`, `scd2_snapshot`, `scd2_merge` and `scd2_stream_task` are normalized into the two v2 dimensions internally.

Reusable parameters stay typed and bounded. Metadata must not describe joins, filters, CASE expressions, aggregations or other business transformations.

## Readable dbt models

For ordinary model materializations, project SQL uses one small configuration macro followed by normal SQL:

```sql
{{ enterprise_snowflake_framework.esf_apply_dataset_config('current_merge') }}

select
    entity_id,
    value,
    source_updated_at,
    source_sequence
from {{ source('bronze', 'source_entity') }}
```

`esf_apply_dataset_config` configures materialization only. It does not generate business SQL.

SCD2 full-change event history remains a dedicated multi-statement technical primitive because it needs ordering, delete semantics and late-arrival correctness. The domain staging/event-shape model remains readable SQL and the technical apply step remains inside the framework.

## Capture versus processing

External ingestion remains outside this framework. Openflow, Snowpipe, Kafka connectors, Fivetran, Airbyte or a custom loader may land data into Bronze.

RAW/source contracts describe landed-source semantics such as:

```text
capture archetype
fidelity
checkpoint kind
ordering/idempotency columns
bootstrap handoff
change semantics
```

The framework owns post-ingestion processing from the Bronze contract onward, plus technical runtime control.

## Git configuration and PLATFORM_CONTROL

Git is the configuration source of truth. Validation runs before dbt receives metadata.

For every validated dataset the framework produces:

```text
canonical JSON
SHA-256 config hash
bounded config snapshot
```

Runtime values such as run IDs, PR numbers and query tags are intentionally excluded from the config hash.

Successful stable deployment registers the immutable snapshot through the platform-provisioned domain API:

```text
PLATFORM_CONTROL.CONFIG.<DOMAIN>_REGISTER_DATASET_CONFIG_SNAPSHOT
```

The framework never directly DMLs the shared `DATASET_CONFIG_SNAPSHOT` base table.

Mutable runtime state remains separate:

```text
PLATFORM_CONTROL.OPERATIONS.PIPELINE_RUN
PLATFORM_CONTROL.OPERATIONS.PIPELINE_CHECKPOINT
PLATFORM_CONTROL.OPERATIONS.PIPELINE_BOOTSTRAP
PLATFORM_CONTROL.OPERATIONS.PIPELINE_CHECK_RESULT
```

## Reusable delivery workflows

### PR workspace

`.github/workflows/pr-workspace.yml` creates/drops guarded `PR_<n>_<MEDALLION_LAYER>` schemas using the project-specific CI identity. It does not run untrusted PR business code while holding Snowflake credentials.

### Stable deployment

`.github/workflows/project-deploy.yml` is the reusable DEV/UAT/PROD deployment contract.

It requires immutable project/framework SHAs and then performs:

```text
verify project SHA is in main history
  -> verify project framework pin
  -> build validated dbt execution context from Git metadata
  -> authenticate with protected-environment WIF
  -> dbt build using validated vars
  -> register dataset config snapshots only after successful build
```

The resolved default schema is `SILVER_STAGING`.

Domain repositories should expose only a thin `workflow_dispatch` wrapper. The preferred UX is: choose `dev`, `uat` or `prod`; the wrapper passes the selected workflow revision SHA to this reusable workflow. The reusable workflow still rejects revisions that are not reachable from `main`.

Promotion changes environment, not source revision:

```text
same project SHA
DEV -> UAT -> PROD
```

## Current reusable primitives

Implemented areas include:

```text
workspace/target/query-tag resolution
metadata and RAW contract validation
bounded dbt vars + deterministic config snapshots
full-refresh / append / keyed merge / explicit SCD1
metadata-driven SCD2 snapshot/event/stream-task paths
capture/checkpoint/bootstrap helpers
quality/reconciliation helpers
domain-scoped operational/control-plane API helpers
reusable PR workspace and stable deployment workflows
```

Snowflake-native TABLE / STREAM / TASK / MERGE / Snowflake Scripting remains the reliability baseline. Dynamic Tables are an optional declarative execution mode where the target semantics and Snowflake feature set fit.

## Proof boundary

Framework CI proves source/static behavior: Python utilities, metadata validation, dbt parse/render, SCD correctness oracles, workspace naming and reusable workflow contracts.

It does **not** prove live Snowflake authentication, grants, concurrency, transaction behavior, performance, source snapshot consistency or recovery. Those remain explicit DEV integration gates.

Projects consume immutable framework SHAs and upgrade deliberately; they must not follow framework `main` implicitly.
