# Run Evidence Integration

## Goal

A health/SLA control plane is useful only when every pipeline stage emits trustworthy run evidence. This design connects source-specific ingestion, generated Silver procedures, Snowflake-native Dynamic Table refresh evidence and dbt to the domain-local observability surfaces without creating a universal orchestrator.

```text
source-specific ingestion -> CONTROL.INGESTION_RUN
explicit Silver apply     -> CONTROL.PIPELINE_RUN
Dynamic Table refresh     -> Snowflake native refresh history
dbt on-run-end            -> CONTROL.DBT_RUN
                                      |
                                      v
                          CONTROL.DATASET_HEALTH
                                      |
                                      v
                               SLA / INCIDENT
```

## Ingestion

Ingestion technology remains domain-owned. The Framework exposes a small optional SQL ledger API:

```text
BEGIN_INGESTION_RUN
COMPLETE_INGESTION_RUN
FAIL_INGESTION_RUN
```

These procedures record an attempt, completion timestamp, source event range, Bronze publication, row count, external run id and error evidence. They do not schedule ingestion, own connector checkpoints or trigger pattern routing.

Managed connectors remain authoritative for their own runtime state. If they cannot call the ledger API directly, a domain may reconcile their native operational history into `INGESTION_RUN`.

## Silver execution evidence

Stream/Task and batch-SQL implementations with an explicit generated apply procedure write `CONTROL.PIPELINE_RUN` at RUNNING/SUCCESS/FAILED boundaries. Dynamic Tables do not fabricate these rows; their native refresh history is normalized separately by control migration 100.

Control migration 110 introduces the canonical explicit-pipeline metric contract:

```text
METRICS_CONTRACT_VERSION
ROWS_READ
ROWS_AFFECTED
AFFECTED_BUSINESS_KEYS
SILVER_DATA_MAX_AT       -> DATA_MAX_AT in CONTROL.PIPELINE_EXECUTION_METRICS_V
SILVER_PUBLISHED_AT      -> PUBLISHED_AT in CONTROL.PIPELINE_EXECUTION_METRICS_V
DML_QUERY_ID
METRICS
STATUS
```

`ROWS_AFFECTED` has one definition for every generated apply pattern: it is `SQLROWCOUNT` captured immediately after the primary Silver DML identified by `DML_QUERY_ID`. `DML_QUERY_ID` is captured with Snowflake Scripting `SQLID` immediately after that statement, before logging or other SQL can change session query position.

`AFFECTED_BUSINESS_KEYS` is the number of distinct logical keys considered by that run. Pattern-specific physical work belongs in `METRICS`, for example:

```text
append       -> output_rows_inserted
full_refresh -> snapshot_rows_written
scd1         -> merge_rows_affected
scd2         -> events_inserted, history_rows_deleted, history_rows_rebuilt,
                plus the query id for each of those DML statements
```

The original `ROWS_INSERTED`, `ROWS_UPDATED` and `ROWS_DELETED` columns remain in `CONTROL.PIPELINE_RUN` for historical compatibility. They are not a cross-pattern contract. In particular, `SQLROWCOUNT` after a Snowflake `MERGE` is total rows affected, so new SCD1 procedures must not label it `ROWS_UPDATED`. New generated code only fills a legacy breakdown field when its meaning is unambiguous.

`CONTROL.PIPELINE_EXECUTION_METRICS_V` is the stable read surface for canonical explicit-pipeline metrics and exposes the old fields with `LEGACY_` prefixes for audit.

Because generated dataset SQL is domain-owned after scaffold, migration 110 does not rewrite already-generated apply procedures. Existing implementations keep their historical behavior until a domain creates/reviews a new implementation version or manually migrates its owned SQL. A future template-provenance/advisory capability can make these affected old implementations discoverable without rewriting them.

## dbt

New domain repos include an `on-run-end` macro based on dbt's documented `results` context. Each model Result supplies status, execution time, message and adapter response.

Per-dataset Gold health is opt-in. A model must declare:

```yaml
config:
  meta:
    esf_dataset_id: fleet_mssql.customer
```

This prevents a cross-domain or multi-dataset business mart from being falsely treated as the Gold publication of one logical dataset.

For a mapped model, the macro records the latest successful Silver data timestamp available at build completion. It does not invent a Gold business-event timestamp. Domains that need a stronger Gold data-time contract should add explicit domain-owned evidence.

## Git identity

Deployment automation should expose the immutable project revision as `ESF_PROJECT_GIT_SHA`. The dbt macro records it when present. Local developer runs may leave it blank.

## Upgrade behavior

`init-project` remains append-only:

- new repos receive all current control migrations including 110, dbt macro, dbt documentation and the `on-run-end` hook;
- old repos receive missing new files but their existing `control_plane/deploy_manifest.txt`, generated dataset SQL and `dbt/dbt_project.yml` are never rewritten;
- engineers review `esf control-plan` and append newly adopted control migrations without reordering already-recorded migration history;
- new generated apply procedures require migration 110 before deployment.

This keeps operational observability standardized without turning Framework upgrades into hidden production behavior changes.
