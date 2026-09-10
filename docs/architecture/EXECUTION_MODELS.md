# Semantic patterns and execution models

## Decision

A logical dataset's **pattern** describes data semantics. An implementation version's **execution_model** describes how Snowflake maintains that semantic result.

These are deliberately separate concepts.

```text
logical dataset: fleet_mssql.customer
  pattern: scd1

  v1
    execution_model: stream_task

  v2
    execution_model: dynamic_table
```

Changing execution technology therefore creates a new implementation version; it does not redefine the logical dataset's semantic pattern.

## Ownership boundary

The source manifest remains small and logical:

```yaml
datasets:
  customer:
    pattern: scd1
    raw_contract: contracts/raw/fleet_mssql/customer.yml
```

Do not put `execution_model` in `config/sources/*.yml`.

Each generated `version.yml` owns the implementation choice:

```yaml
schema_version: 1
version:
  dataset: fleet_mssql.customer
  id: v2
  initial_status: development
  activation: explicit
  execution_model: dynamic_table
  dynamic_table:
    target_lag: 5 minutes
    warehouse: WH_TRANSPORT_TRANSFORM
    refresh_mode: incremental
```

Pre-0.19 version files did not declare `execution_model`. They remain readable as the historical implicit model: standard patterns use `stream_task`; `custom` uses `custom`. The Framework does not rewrite those domain-owned files.

## Supported compatibility matrix

0.19 intentionally supports only combinations whose semantics are explicit and tested.

| Pattern | stream_task | dynamic_table | batch_sql | custom |
| --- | --- | --- | --- | --- |
| append | supported | not yet supported | not yet supported | no |
| full_refresh | supported | supported | supported | no |
| scd1 | supported | supported | not yet supported | no |
| scd2 | supported | **not yet supported** | not yet supported | no |
| custom | no | no | no | supported |

Unsupported combinations fail validation/scaffolding. The Framework does not synthesize missing semantics merely to make the matrix look complete.

In particular, `scd2 + dynamic_table` remains disabled until the existing history/tombstone/reinsert/late-arrival/replay contract has an equivalent declarative implementation and real Snowflake certification.

## Execution models

### stream_task

The existing Snowflake-native mutation model:

```text
BRONZE
  -> Stream/readiness
  -> Task
  -> dataset-local apply procedure
  -> SILVER physical relation
  -> dataset-local validation procedure
```

`CONTROL.PIPELINE_RUN` is the primary Silver execution evidence.

### dynamic_table

A declarative SELECT-defined Silver implementation managed by Snowflake Dynamic Tables.

0.19 generates no fake Stream, Task, apply procedure or replay procedure for a Dynamic Table version. A typical candidate directory contains:

```text
version.yml
001_dynamic_table.sql
020_validate.sql
025_compare.sql
040_register.sql
050_publish.sql
060_policy.sql
deploy_manifest.fragment.txt
README.md
```

Only migration files in `deploy_manifest.fragment.txt` are applied automatically. Candidate publication remains a no-op until explicit release.

SCD1 is rendered as the latest valid row per business key using the RAW contract's ordering evidence and tombstone semantics. Full-refresh is rendered as a declarative projection of the current Bronze snapshot.

The Framework explicitly sets `REFRESH_MODE` to `INCREMENTAL` or `FULL`; it does not generate `AUTO`, because silent mode selection would make cost/performance behavior less deterministic between releases.

`TARGET_LAG` is version runtime configuration, not a logical dataset SLA. The existing `CONTROL.SLA_POLICY` remains the business-facing latency/freshness policy.

### batch_sql

0.19 supports `batch_sql` for `full_refresh` only. It retains explicit dataset-local procedures but owns no Framework Task/Stream scheduler. External scheduling remains outside the Framework and `CONTROL.PIPELINE_RUN.TASK_NAME` is recorded as NULL.

This is intentionally narrower than inventing batch semantics for event-driven APPEND/SCD patterns.

### custom

`custom` remains domain-authored. The Framework does not invent orchestration or transformation logic for it.

## Control-plane representation

`CONTROL.DATASET.PATTERN` remains logical-dataset metadata.

Apply-once migration `090_dataset_execution_model.sql` adds version-level fields:

```text
CONTROL.DATASET_VERSION.EXECUTION_MODEL
CONTROL.DATASET_VERSION.PRIMARY_RUNTIME_OBJECT
```

Legacy Task/Stream/apply columns remain for compatibility and useful diagnostics. They are NULL when they do not apply.

Migration `100_dynamic_table_observability.sql` normalizes native Snowflake `INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY` into `CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V` and updates `CONTROL.DATASET_OBSERVABILITY_V` to choose execution evidence for the active version:

```text
stream_task / batch_sql -> CONTROL.PIPELINE_RUN
dynamic_table           -> native Dynamic Table refresh history
```

No fake `PIPELINE_RUN` row is inserted for a Dynamic Table refresh.

## Lifecycle

Lifecycle SQL follows the selected version's execution model:

```text
stream_task
  pause/resume -> ALTER TASK ... SUSPEND/RESUME

dynamic_table
  pause/resume -> ALTER DYNAMIC TABLE ... SUSPEND/RESUME

batch_sql
  no Framework-owned scheduler; coordinate the external scheduler explicitly
```

Soft decommission stops every known version according to its own model and still preserves data/audit objects.

## Repair

Procedural versions use their explicit replay/rebuild procedure.

A Dynamic Table candidate has no fake replay procedure. `repair-sql` generates an explicit manual `ALTER DYNAMIC TABLE ... REFRESH` and rejects `--from/--to`. If the committed Dynamic Table definition itself is wrong after its migration was applied, create a later implementation version rather than editing the applied migration.

## Release and rollback

Release can cross execution technologies.

For example:

```text
scd1 v1 stream_task
  -> scd1 v2 dynamic_table
```

The generated activation operation:

1. explicitly refreshes the candidate Dynamic Table;
2. replaces only the stable consumer view using `COPY GRANTS`;
3. updates version/control identity;
4. retires the old implementation runtime last.

Rollback performs the inverse using each version's own execution model.

## DQ

Dynamic Table versions keep dataset-local DQ SQL, but 0.19 does not create a fake validation procedure or validation Task merely for structural symmetry. The generated `020_validate.sql` records explicit DQ evidence when run during deployment/release validation or an operator-owned validation cadence.

If a domain needs continuous business DQ after every Dynamic Table refresh, add a domain-owned validation cadence rather than coupling transformation semantics back to a Task runtime.

## Certification

The trusted Snowflake certification suite now contains a cross-technology scenario:

```text
SCD1 v1 stream_task
  -> historical/late/out-of-order semantics
  -> candidate v2 dynamic_table
  -> Dynamic Table initialization
  -> post-candidate Bronze event
  -> v1 apply + v2 manual refresh
  -> equivalent current state
  -> native refresh-history evidence
  -> DQ + version comparison
  -> COPY GRANTS cutover
  -> health reads execution_model=dynamic_table
  -> rollback to v1
```

The code path is implemented in 0.19, but an exact Framework SHA may only be described as Snowflake-certified after the trusted credentialed workflow actually returns `CERTIFIED` for that SHA. Static CI alone is not certification.

## What remains deliberately outside this feature

- dbt does not become a Bronze-to-Silver executor;
- Dynamic Table SCD2 is not enabled;
- no metadata-driven runtime router is added;
- no execution model is inferred from source profiling;
- no automatic production cutover occurs;
- no Dynamic Table definition is silently rewritten after an apply-once migration is recorded.
