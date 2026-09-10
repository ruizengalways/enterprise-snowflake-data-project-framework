# __PROJECT_NAME__

This repository owns production data-pipeline source code and operational control for one Snowflake business domain.

```text
Source -> Ingestion -> BRONZE -> Stream/readiness -> Task -> domain-owned SQL/procedure -> SILVER -> dbt -> GOLD -> SEMANTIC
```

A domain may contain many source systems. New generated Snowflake object names preserve the source boundary so same-named datasets from different sources do not collide by default.

The Enterprise Snowflake Framework creates starters, but ownership is append-only:

```text
missing ownership unit -> create
existing ownership unit -> never overwrite
```

This applies to source-manifest dataset declarations, dataset roots, candidate `versions/vN/` directories and generated SLA/lifecycle/repair/release files.

This project owns a domain-local control plane under `control_plane/`. The committed SQL creates this domain's `CONTROL` schema, operational ledgers, version/SLA state, health evaluation, incident lifecycle and dashboard-ready views. It is not a shared global runtime database.

Operational evidence follows one domain contract:

```text
source-specific ingestion -> CONTROL.INGESTION_RUN
Silver apply procedure    -> CONTROL.PIPELINE_RUN
dbt model result          -> CONTROL.DBT_RUN
```

See `ingestion/RUN_EVIDENCE.md` and `dbt/README.md`. Ingestion remains source-specific; the ledger API does not replace Openflow, Snowpipe, Kafka, Talend, ADF or project-specific ingestion.

Enterprise monitoring reads the domain's stable `CONTROL.ENTERPRISE_HEALTH_EXPORT_V` / `CONTROL.DOMAIN_HEALTH_SUMMARY_V`; see `docs/ENTERPRISE_HEALTH_EXPORT.md`. Cross-domain monitoring remains read-only.

For a reviewed RAW contract, declare the dataset first and inspect the plan before scaffolding:

```bash
esf control-plan --project-root .
esf add-source <source_id> --project-root .
esf add-dataset <dataset> \
  --source <source_id> \
  --pattern scd2 \
  --project-root .
esf plan --source <source_id> --project-root .
esf scaffold-preview <dataset> --source <source_id> --project-root .
esf scaffold-all --source <source_id> --project-root .
esf validate --project-root .
```

`add-dataset` only appends a missing `datasets.<dataset>` declaration to the source manifest. It defaults `raw_contract` to `contracts/raw/<source>/<dataset>.yml`, requires that contract to exist under the same source, preserves existing YAML comments/order through round-trip editing, never edits an existing dataset declaration and never scaffolds SQL.

Define an SLA only after the domain agrees the operational expectation:

```bash
esf sla-sql <dataset> freshness_v1 \
  --source <source_id> \
  --stage END_TO_END \
  --cadence CONTINUOUS \
  --max-freshness-seconds 600 \
  --project-root .
```

Generate explicit lifecycle operations instead of directly mutating production from the CLI:

```bash
esf lifecycle-sql <dataset> pause_incident_123 \
  --source <source_id> --action pause --version v1 --project-root .

esf lifecycle-sql <dataset> decommission_2026q4 \
  --source <source_id> --action decommission --project-root .
```

Candidate / repair / release flow:

```bash
esf scaffold-version <dataset> v2 --source <source_id> --project-root .
esf repair-plan <dataset> --source <source_id> --problem silver --project-root .
esf repair-sql <dataset> v2 --source <source_id> --project-root .
esf release-sql <dataset> --source <source_id> --from-version v1 --to-version v2 --project-root .
```

`control-plan` and `repair-plan` are read-only. `sla-sql`, `lifecycle-sql`, `repair-sql` and `release-sql` generate reviewable files only. They do not connect to Snowflake or execute production changes.

For domain shutdown, follow `docs/DOMAIN_DECOMMISSION.md`. Decommission is staged: stop movement and consumers first, preserve evidence for the agreed retention window, then perform physical/infrastructure cleanup in a separate approved change.
