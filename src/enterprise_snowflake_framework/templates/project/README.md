# __PROJECT_NAME__

This repository owns production data-pipeline source code and operational control for one Snowflake business domain.

```text
Source -> Ingestion -> BRONZE -> SILVER -> dbt -> GOLD_MARTS -> SEMANTIC
                         ^
                         | explicit Stream/Task, Dynamic Table, batch SQL or domain-owned custom execution

CONTROL = cross-cutting operational evidence, health, lifecycle and release state
```

A domain may contain many source systems. New generated Snowflake object names preserve the source boundary so same-named datasets from different sources do not collide by default.

The Enterprise Snowflake Framework creates starters, but ownership is append-only:

```text
missing ownership unit -> create
existing ownership unit -> never overwrite
```

This applies to RAW contract drafts/formal contracts, source-manifest dataset declarations, dataset roots, candidate `versions/vN/` directories and generated operational bundles.

This project owns a domain-local control plane under `control_plane/`. The committed SQL creates this domain's `CONTROL` schema, operational ledgers, version/SLA state, quality evidence, health evaluation, incident lifecycle and dashboard-ready views. It is not a shared global runtime database.

Operational evidence follows one domain contract:

```text
source-specific ingestion  -> CONTROL.INGESTION_RUN
explicit Silver apply      -> CONTROL.PIPELINE_RUN
Silver validation          -> CONTROL.DQ_RESULT
dbt model result           -> CONTROL.DBT_RUN
reconciliation code        -> CONTROL.RECONCILIATION_RESULT
release/rollback attempt   -> CONTROL.RELEASE_RUN
health cadence operation   -> CONTROL.HEALTH_EVALUATION_CHANGE
```

See `ingestion/RUN_EVIDENCE.md`, `operations/reconciliation/README.md`, `operations/health/README.md` and `dbt/README.md`. Ingestion remains source-specific; the ledger API does not replace Openflow, Snowpipe, Kafka, Talend, ADF or project-specific ingestion.

Standard scaffolded `020_validate.sql` is dataset-local source code. It records small structural checks after a successful apply. Business DQ rules remain domain-owned. Reconciliation logic is never inferred; the project computes the comparison valid for its source/pattern and records normalized evidence when useful.

Enterprise monitoring reads the domain's stable `CONTROL.ENTERPRISE_HEALTH_EXPORT_V` / `CONTROL.DOMAIN_HEALTH_SUMMARY_V`. Cross-domain monitoring remains read-only. Active-version DQ/reconciliation failures can affect production health; candidate evidence remains for shadow/release review.

## RAW contract -> dataset workflow

Source profiling/discovery is outside this Framework. If a formal RAW contract is not ready yet, create an isolated draft that production validation ignores:

```bash
esf add-source <source_id> --project-root .
esf raw-contract-draft <dataset> --source <source_id> --project-root .
# Edit contracts/drafts/<source_id>/<dataset>.yml and resolve every TODO.
esf raw-contract-finalize <dataset> --source <source_id> --project-root .
```

`raw-contract-finalize` validates the reviewed draft and moves the exact bytes into `contracts/raw/<source>/<dataset>.yml`. It never overwrites an existing formal contract and does not declare or scaffold the dataset.

Then register the reviewed contract and inspect the plan before scaffolding:

```bash
esf add-dataset <dataset> --source <source_id> --pattern scd2 --project-root .
esf plan --source <source_id> --project-root .
esf scaffold-preview <dataset> --source <source_id> --project-root .
esf scaffold-all --source <source_id> --project-root .
esf validate --project-root .
```

`add-dataset` only appends a missing dataset declaration to the source manifest. Existing declarations remain domain-owned.

## Version execution policy

Logical pattern belongs to the dataset. Execution technology and runtime policy belong to the implementation version.

For a new `stream_task` version, the Framework can explicitly declare Task warehouse, minimum trigger interval, timeout, suspend-after-failures and optional error integration. Those settings are not SLA policy and do not belong in the source manifest.

Dynamic Table target lag, warehouse and refresh mode are likewise version execution settings, not logical freshness guarantees.

## Control Plane upgrades

Run:

```bash
esf init-project --project-root .
esf control-plan --project-root .
```

when adopting Framework Control Plane upgrades. `init-project` may materialize newly introduced migration files, but it never rewrites this repository's existing `control_plane/deploy_manifest.txt`. Review and append newly adopted migrations explicitly without reordering applied history.

Migration `130_health_evaluation_cadence.sql` makes the **domain health evaluator schedule** configurable without changing released `040_health_task.sql`. Migration 130 only creates an audit/read contract; it does not silently retune the Task.

After 130 is applied, generate a reviewed cadence change with an explicit final Task state:

```bash
esf health-cadence-sql health-every-5m \
  --interval-seconds 300 \
  --reason "Five-minute health evaluation is appropriate for this domain" \
  --resume-after \
  --project-root .
```

Use `--leave-suspended` when that is the intended final state. Review `operations/health/<operation-id>/preflight.sql`, `operation.sql` and `postflight.sql`; the CLI never executes them.

Domain health evaluator cadence is operational control policy. It is deliberately separate from logical dataset SLA.

## SLA, lifecycle, candidate and repair operations

Define SLA only after the domain agrees the operational expectation:

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
```

Candidate / repair / release flow:

```bash
esf scaffold-version <dataset> v2 --source <source_id> --project-root .
esf repair-plan <dataset> --source <source_id> --problem silver --project-root .
esf repair-sql <dataset> v2 --source <source_id> --project-root .
esf release-sql <dataset> --source <source_id> --from-version v1 --to-version v2 --project-root .
```

Review candidate runtime, DQ and version-comparison evidence before cutover. `control-plan`, `repair-plan` and `upgrade-plan` are read-only. SQL-generating commands create reviewable files only; they do not connect to Snowflake or execute production changes.

For domain shutdown, follow `docs/DOMAIN_DECOMMISSION.md`. Decommission is staged: stop movement and consumers first, preserve evidence for the agreed retention window, then perform physical/infrastructure cleanup in a separate approved change.
