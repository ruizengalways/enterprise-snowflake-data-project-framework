# Dataset control plane and configuration snapshots

## Purpose

A business domain can contain many physical sources and hundreds of datasets. Those datasets may use different capture and target/history behaviors without creating a separate control system per source.

The framework separates four concerns:

```text
Git dataset/source contracts
        |
        v
validated technical configuration
        |
        +--> dbt/runtime strategy dispatch
        |
        +--> immutable deployment config snapshot

PLATFORM_CONTROL runtime state
  PIPELINE_RUN
  PIPELINE_CHECKPOINT
  PIPELINE_BOOTSTRAP
  PIPELINE_CHECK_RESULT
```

## Capture strategy is not load/history strategy

How data is acquired from a source and how the target is maintained are independent dimensions.

Examples:

| Dataset | Capture | Target/history |
| --- | --- | --- |
| patient | full-change CDC | SCD2 |
| provider | watermark | SCD1 merge |
| claim | full refresh | full refresh |
| lab_result | API cursor | append-only |

The RAW/source contract owns capture semantics such as checkpoint kind, ordering, idempotency and bootstrap handoff. Dataset metadata owns the target load/history strategy.

Supported standard load strategy vocabulary includes:

```text
full_refresh
append_only
incremental_merge
scd1_merge
scd2_snapshot
scd2_merge
scd2_stream_task
```

`scd1_merge` is explicit for current-state dimension semantics; `incremental_merge` remains available for generic keyed upsert datasets.

## Do not build one giant control table

Strategy-specific parameters stay in typed Git metadata. SCD2 fields exist only for SCD2 datasets. Capture-specific fields stay in the RAW contract. This avoids a wide table dominated by null columns and boolean flags.

Likewise, do not create one checkpoint/run table per source or per dataset. Runtime state is structurally stable and keyed by project/dataset identity.

## Git is the configuration source of truth

Project YAML/JSON contracts are validated in CI before they are exposed to dbt. The framework builds a bounded technical configuration for each dataset and a separate deterministic deployment snapshot.

A snapshot contains:

- validated dataset technical metadata;
- bounded source-contract semantics;
- dataset/raw-contract schema versions;
- canonical JSON;
- SHA-256 configuration hash.

Runtime values such as `run_id`, PR number and query tag are intentionally excluded from the configuration hash.

The framework exposes snapshots through `esf_dataset_snapshots` and renders calls only to the platform-provisioned domain procedure:

```text
PLATFORM_CONTROL.CONFIG.<DOMAIN>_REGISTER_DATASET_CONFIG_SNAPSHOT
```

It never directly inserts, updates or deletes the shared base table.

## Snowflake snapshot table is audit state, not editable config

`PLATFORM_CONTROL.CONFIG.DATASET_CONFIG_SNAPSHOT` answers questions such as:

- Which validated configuration was deployed for this dataset at this Git revision?
- Did the SCD/load/capture parameters change between releases?
- Which config hash corresponds to a historical deployment?

It is not a UI-editable parameter store. Production configuration changes go through Git review and CI.

A repeated registration of the same project/environment/dataset/Git SHA and the same content is idempotent. Reusing the same Git SHA with conflicting content must fail closed.

## Database and Medallion boundary

Database placement does not encode source or load strategy. A domain database uses stable Medallion-aligned schemas such as:

```text
BRONZE
SILVER_STAGING
SILVER_INTERMEDIATE
SILVER_CANONICAL
GOLD_MARTS
GOLD_SEMANTIC
DQ
```

Multiple ordinary sources coexist in `BRONZE`; source identity remains in metadata and object naming. A source-specific schema is a governance exception, not the default connector boundary.

## Custom behavior

Metadata should describe reusable technical behavior, not become a programming language. If a dataset needs genuinely source/domain-specific logic, declare `implementation: custom` and keep that implementation explicit in the domain repository while still using the shared runtime/control contracts where appropriate.
