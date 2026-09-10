# Enterprise Snowflake Data Project Toolkit

This repository is intentionally **not a universal data runtime framework**.

Its responsibility is:

```text
Framework owns project creation and reusable operating patterns.
Domain repositories own project evolution and production transformation code.
```

The toolkit creates readable project/source/dataset starters, validates contracts, provides domain-local operational-control foundations, and supplies reusable CI/CD guardrails. Generated SQL is ordinary source code committed to the domain repository. CONTROL and SILVER deployment uses checksum-locked apply-once migrations; deployment does not regenerate production transformation SQL from metadata or replay every historical SQL file on every release.

## Architecture boundary

Canonical logical architecture vocabulary is:

```text
Source
  -> source-specific ingestion
  -> Bronze
  -> Silver
  -> Gold / Marts
  -> Semantic

Control = cross-cutting operational evidence, health and release state
```

Default physical schemas inside a domain database are:

```text
BRONZE
SILVER
GOLD_MARTS
SEMANTIC
CONTROL
```

Logical names and physical schema identifiers are deliberately separate. `Gold / Marts` is the architecture term while `GOLD_MARTS` is the default physical schema; do not rename production schemas merely to make prose identical. See `docs/architecture/NAMING_AND_LAYERS.md`.

Ingestion remains source-specific. Openflow, Snowpipe, Kafka connectors, Talend/ADF/Informatica, REST/API code and scheduled loads can coexist. Source profiling/discovery is deliberately outside this Framework.

## One domain repo, many sources

A business domain is normally a repository plus one Snowflake database per environment. Run `esf init-project` inside the domain repo.

```text
enterprise-snowflake-transport-analytics/
├── config/sources/
├── contracts/
│   ├── drafts/
│   └── raw/
├── ingestion/
├── silver_processing/
├── control_plane/
├── dbt/
└── operations/
```

A domain can contain many source systems. Source identity remains a durable organization boundary:

```text
config/sources/fleet_mssql.yml
contracts/raw/fleet_mssql/customer.yml
ingestion/fleet_mssql/
silver_processing/fleet_mssql/customer/
```

Generated object names preserve that source boundary, for example:

```text
BRONZE.FLEET_MSSQL_CUSTOMER
SILVER.FLEET_MSSQL_CUSTOMER_V1_HISTORY
SILVER.FLEET_MSSQL_CUSTOMER_CURRENT
```

This avoids collisions when multiple sources contain a `customer` dataset. A new source does **not** require a new database by default. Domain/workload roles, warehouses, query tags and account/environment boundaries provide better cost and ownership controls than treating every source as a database boundary.

## RAW contract authoring gate

RAW contracts are reviewed engineering declarations, not discovery output. The Framework does not infer business keys, timestamps, ordering, CDC/delete semantics, capture fidelity or SCD pattern.

Incomplete work stays outside the production contract boundary:

```text
contracts/drafts/<source>/<dataset>.yml
```

Only finalized contracts live under:

```text
contracts/raw/<source>/<dataset>.yml
```

Typical flow:

```bash
esf add-source fleet_mssql --project-root .
esf raw-contract-draft customer --source fleet_mssql --project-root .
# Resolve every TODO in the draft.
esf raw-contract-finalize customer --source fleet_mssql --project-root .
esf add-dataset customer --source fleet_mssql --pattern scd2 --project-root .
esf plan --source fleet_mssql --project-root .
esf scaffold-preview customer --source fleet_mssql --project-root .
esf scaffold scd2 customer --source fleet_mssql --project-root .
```

`raw-contract-draft` creates a draft once and never overwrites it. `raw-contract-finalize` refuses unresolved TODO values, validates the reviewed contract, and promotes the exact reviewed content into `contracts/raw/`. It does not add a dataset declaration or scaffold Silver SQL. See `docs/architecture/RAW_CONTRACT_AUTHORING.md`.

## Logical pattern vs execution model

Dataset semantics and implementation technology are different contracts.

Logical dataset pattern:

```text
append
full_refresh
scd1
scd2
custom
```

Version-level execution model:

```text
stream_task
dynamic_table
batch_sql
custom
```

The source manifest owns semantic `pattern` and `raw_contract`. `execution_model` belongs to each implementation version. `procedure` is an implementation artifact, not an execution model.

Supported combinations intentionally fail closed outside this matrix:

```text
append       + stream_task   = supported
full_refresh + stream_task   = supported
full_refresh + dynamic_table = supported
full_refresh + batch_sql     = supported
scd1         + stream_task   = supported
scd1         + dynamic_table = supported
scd2         + stream_task   = supported
custom       + custom        = domain-owned
```

See `docs/architecture/EXECUTION_MODELS.md`.

## Generated-once ownership

A standard Stream/Task implementation typically owns:

```text
README.md
pipeline.yml
version.yml
001_objects.sql
010_apply.sql
015_replay.sql
020_validate.sql
025_compare.sql
030_task.sql
040_register.sql
050_publish.sql
060_policy.sql
deploy_manifest.fragment.txt
```

Dynamic Table implementations intentionally omit fake Stream/Task/apply/replay files and use native Dynamic Table refresh evidence.

The core ownership rule is:

```text
NOT EXISTS -> create the requested ownership unit
EXISTS     -> DOMAIN OWNED FOREVER
```

There is deliberately no scaffold `--force`. A Framework upgrade may add a new project-level migration/template/runbook, but it does not rewrite an existing domain-owned dataset version.

`DOMAIN OWNED FOREVER` describes scaffold ownership. Separately, once a CONTROL/SILVER migration path has been applied/baselined/remediated in an environment, that migration is immutable there. Future behavior changes use a later migration path or a new implementation version.

## Domain-local Control Plane

Each domain owns its writable `CONTROL` schema. Do not put all domains into one shared writable runtime control database. Enterprise monitoring consumes stable read-only exports instead.

A fresh 0.22 project contains committed Control migrations through `120_release_readiness.sql`:

```text
001_objects.sql
010_observability_views.sql
020_refresh_health.sql
030_sla_incident_lifecycle.sql
040_health_task.sql
050_dataset_lifecycle_status.sql
060_run_evidence_api.sql
070_enterprise_health_export.sql
080_data_quality_reconciliation.sql
090_dataset_execution_model.sql
100_dynamic_table_observability.sql
110_pipeline_execution_metrics.sql
120_release_readiness.sql
```

Released numbered migrations are immutable. Never edit 001..120 in place after release; append a later migration.

Key later contracts are:

```text
090_dataset_execution_model.sql
  -> version execution model and primary runtime identity

100_dynamic_table_observability.sql
  -> Dynamic Table native refresh evidence normalized into domain observability

110_pipeline_execution_metrics.sql
  -> canonical explicit-pipeline rows/query-id metrics

120_release_readiness.sql
  -> candidate/release readiness, active/candidate invariants and release audit surfaces
```

Operational evidence remains normalized, not centralized runtime control:

```text
source-specific ingestion -> CONTROL.INGESTION_RUN
explicit Silver apply     -> CONTROL.PIPELINE_RUN
Silver validation         -> CONTROL.DQ_RESULT
dbt model result          -> CONTROL.DBT_RUN
reconciliation code       -> CONTROL.RECONCILIATION_RESULT
release/rollback attempt  -> CONTROL.RELEASE_RUN
```

## Canonical explicit-run metrics

New generated explicit apply procedures use metrics contract version 1. The important invariant is:

```text
ROWS_AFFECTED = SQLROWCOUNT for the primary Silver DML
DML_QUERY_ID  = SQLID captured immediately after that same DML
```

Pattern-specific physical work belongs in `METRICS`; universal `ROWS_INSERTED / ROWS_UPDATED / ROWS_DELETED` semantics are not fabricated for patterns such as SCD1/SCD2.

`CONTROL.PIPELINE_EXECUTION_METRICS_V` is the stable read surface. Historical row-count columns remain available with legacy semantics. See `docs/architecture/RUN_EVIDENCE.md`.

## Unified observability without unified runtime mechanics

The Framework unifies evidence contracts, not execution technologies:

```text
explicit Stream/Task or batch apply
  -> CONTROL.PIPELINE_RUN
  -> CONTROL.PIPELINE_EXECUTION_METRICS_V

Dynamic Table
  -> INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V

both
  -> CONTROL.DATASET_OBSERVABILITY_V
  -> health / SLA / incidents
```

Do not create fake `PIPELINE_RUN` rows for Dynamic Tables or add a second competing unified execution-health layer without a concrete missing contract.

## Apply-once deployment

`control_plane/deploy_manifest.txt` and `silver_processing/deploy_manifest.txt` are ordered migration manifests, not replay lists.

The reusable deployment path is:

```text
contract validation
  -> control baseline preflight
  -> manifest validation
  -> Snowflake OIDC authentication
  -> bootstrap CONTROL.DEPLOYMENT_HISTORY
  -> esf-migrate deploy
       CONTROL: APPLY new / SKIP identical / BLOCK drift
       SILVER:  APPLY new / SKIP identical / BLOCK drift
  -> dbt debug
  -> dbt build
```

Every migration is identified by repository-relative path, SHA-256 of exact bytes, manifest position, project Git SHA and Framework Git SHA. Same applied path/checksum/order skips. Changed checksum, removed/reordered applied history, duplicate paths, or unresolved `STARTED`/`FAILED` attempts block deployment.

Existing populated environments with empty deployment history require an explicit reviewed baseline. Failed/partial DDL is never automatically retried because Snowflake DDL can commit statement-by-statement. See `docs/architecture/APPLY_ONCE_MIGRATIONS.md`.

## Candidate versions, release and rollback

Candidate versions live under:

```text
silver_processing/<source>/<dataset>/versions/vN/
```

Creating v2 changes zero bytes in v1. The intended release path is:

```text
scaffold candidate
  -> deploy candidate migrations once
  -> bootstrap / replay / refresh
  -> catch up
  -> DQ
  -> active-vs-candidate comparison
  -> hard preflight
  -> explicit cutover
  -> hard postflight
  -> CONTROL.RELEASE_RUN audit
  -> guarded rollback if required
```

`esf release-sql` generates a reviewable operation bundle only:

```text
README.md
preflight.sql
activate.sql
rollback.sql
postflight.sql
```

It never executes production cutover. Candidate registration and release fail closed on active/candidate conflicts. `BLOCKED` evidence has no bypass. `REVIEW_REQUIRED` can be accepted only explicitly with an operator reason. Stable published views are replaced only at this explicit boundary and use `CREATE OR REPLACE VIEW ... COPY GRANTS`.

The Framework keeps `CONTROL.DATASET.CANDIDATE_VERSION` as a single-candidate convenience/lock for now; it does not invent a large lifecycle state machine without real operational transition owners.

## Template provenance and upgrade planning

Framework 0.22 stamps every newly scaffolded implementation version with deterministic provenance:

```yaml
version:
  provenance:
    framework_version: 0.22.0
    template_id: scd2_stream_task
    template_revision: 1
    template_digest: sha256:...
```

The immutable compatibility identity is template id + revision + digest. There is deliberately no `scaffolded_at` timestamp in this identity.

Run the read-only planner with:

```bash
esf upgrade-plan --project-root .
```

It reports `CURRENT`, `UPDATE_AVAILABLE`, `ADVISORY`, `UNKNOWN` or `UNVERIFIED`. Pre-provenance versions remain valid and report `UNKNOWN`; the Framework never inspects SQL to guess their historical template revision. A digest mismatch reports `UNVERIFIED` instead of guessing. The command never edits domain-owned files. See `docs/architecture/TEMPLATE_PROVENANCE.md`.

## Data quality and reconciliation

Generated structural validation writes version-local evidence to `CONTROL.DQ_RESULT`. Standard starter checks are intentionally narrow; business rules remain domain-authored SQL rather than executable rule metadata.

Reconciliation is similarly conservative. Domain/source-specific code computes a valid comparison and may record normalized evidence through `CONTROL.RECONCILIATION_RESULT`; the Framework does not assume row-count equality or infer business reconciliation rules.

Candidate evidence stays isolated from active production health. `ERROR` failures can contribute RED health/incidents; `WARN` failures contribute YELLOW without automatic failure incident creation. See `docs/architecture/DATA_QUALITY_RECONCILIATION.md`.

## SLA, health and enterprise monitoring

SLA belongs to the logical dataset, not to the source manifest or implementation version. Supported cadence models are `CONTINUOUS`, `INTERVAL` and `SCHEDULED_DEADLINE`. Latency and freshness are separate metrics. Execution settings such as Dynamic Table target lag or Task timing are not automatically treated as SLA thresholds.

Each domain exposes stable read-only enterprise health contracts such as:

```text
CONTROL.ENTERPRISE_HEALTH_EXPORT_V
CONTROL.DOMAIN_HEALTH_SUMMARY_V
```

Enterprise monitoring may aggregate those surfaces; writable health state remains domain-local.

The historical released `040_health_task.sql` contains a one-minute health-evaluation schedule. A future configurable cadence must be implemented with a **new migration/configuration mechanism**, never by editing released 040.

## Repair and lifecycle

Repair starts from the latest known-good layer:

```text
Gold wrong / Silver correct   -> rebuild dbt descendants
Silver wrong / Bronze correct -> candidate version + replay
Bronze wrong                  -> repair ingestion, then replay downstream
```

`repair-plan` is read-only. `repair-sql` generates candidate-only repair SQL for review; it does not overwrite active production.

`esf lifecycle-sql` generates pause/resume/soft-decommission SQL and never executes it. Soft decommission preserves data and audit evidence; destructive cleanup belongs to separately approved retention/governance work.

## dbt / Gold / Semantic

dbt starts from trusted Silver and owns downstream Gold/Mart/Semantic transformation. It is desired-state and may run on every deployment after CONTROL/SILVER migrations complete. It is deliberately not the Bronze-to-Silver execution engine in this Framework.

## CLI

```bash
python -m pip install .

esf init-project --project-root .
esf control-plan --project-root .
esf upgrade-plan --project-root .
esf-control-preflight --project-root .

esf add-source fleet_mssql --project-root .
esf raw-contract-draft customer --source fleet_mssql --project-root .
esf raw-contract-finalize customer --source fleet_mssql --project-root .
esf add-dataset customer --source fleet_mssql --pattern scd2 --project-root .
esf plan --source fleet_mssql --project-root .
esf scaffold-preview customer --source fleet_mssql --project-root .
esf scaffold scd2 customer --source fleet_mssql --project-root .
esf scaffold-all --source fleet_mssql --project-root .
esf scaffold-version customer v2 --source fleet_mssql --project-root .

esf sla-sql customer freshness_v1 \
  --source fleet_mssql \
  --stage END_TO_END \
  --cadence CONTINUOUS \
  --max-freshness-seconds 600 \
  --project-root .

esf lifecycle-sql customer pause_incident_123 \
  --source fleet_mssql --action pause --version v1 --project-root .

esf repair-plan customer --source fleet_mssql --problem silver --project-root .
esf repair-sql customer v2 --source fleet_mssql --project-root .
esf release-sql customer --source fleet_mssql \
  --from-version v1 --to-version v2 --project-root .

esf validate --project-root .

# Authenticated apply-once migration runner used by the reusable deployment workflow:
esf-migrate deploy \
  --project-root . \
  --project-git-sha <domain-sha> \
  --framework-git-sha <framework-sha>
```

## Certification boundary

Credential-free PR/main CI validates package installation, released migration immutability, reference projects, dbt parse, unit/contracts and runtime-indirection guardrails.

A Framework SHA is **Snowflake-certified only** when the trusted certification workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA. A skipped certification workflow or green static CI is not equivalent to live Snowflake acceptance.

## Deliberately absent

The toolkit does not contain a universal source-discovery/profiling engine, universal ingestion orchestrator, central generic SCD runtime, runtime metadata routing, deployment-time scaffolding, connector checkpoint ownership, generic executable DQ-rule metadata, automatic reconciliation/business-key/SCD/SLA inference, arbitrary Task orchestration DSL, automatic production repair, automatic migration retry after partial DDL failure, or automatic business Mart/KPI/Semantic generation.
