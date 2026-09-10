# Run Evidence Integration

## Goal

A health/SLA control plane is useful only when every pipeline stage emits trustworthy run evidence. This design connects source-specific ingestion, generated Silver procedures and dbt to the domain-local run ledgers without creating a universal orchestrator.

```text
source-specific ingestion -> CONTROL.INGESTION_RUN
Silver apply procedure    -> CONTROL.PIPELINE_RUN
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

## Silver

Generated append/full-refresh/SCD1/SCD2 apply procedures already write `CONTROL.PIPELINE_RUN` at RUNNING/SUCCESS/FAILED boundaries. That behavior stays dataset-local and explicit in committed SQL.

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

- new repos receive control migration 060, dbt macro, dbt documentation and the `on-run-end` hook;
- old repos receive missing new files but their existing `control_plane/deploy_manifest.txt` and `dbt/dbt_project.yml` are never rewritten;
- engineers explicitly add migration 060 to the old control manifest and opt into the dbt hook after review.

This keeps operational observability standardized without turning Framework upgrades into hidden production behavior changes.
