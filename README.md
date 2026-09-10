# Enterprise Snowflake Data Project Toolkit

This repository is intentionally **not a universal data runtime framework**.

```text
Framework owns project creation and reusable operating patterns.
Domain repositories own project evolution and production transformation code.
```

The toolkit creates readable project/source/dataset starters, validates contracts, supplies domain-local operational-control foundations, and provides reusable CI/CD guardrails. Generated SQL is normal source code committed to the domain repository. CONTROL and SILVER deployment uses checksum-locked apply-once migrations; deployment never regenerates production transformation SQL from runtime metadata.

## Architecture boundary

Canonical logical vocabulary:

```text
Source
  -> source-specific ingestion
  -> Bronze
  -> Silver
  -> Gold / Marts
  -> Semantic

Control = cross-cutting operational evidence, health and release state
```

Default physical schemas:

```text
BRONZE
SILVER
GOLD_MARTS
SEMANTIC
CONTROL
```

Logical vocabulary and physical identifiers are deliberately separate. See `docs/architecture/NAMING_AND_LAYERS.md`.

A business domain normally owns one repository plus one Snowflake database per environment. A domain can contain many source systems; source identity remains explicit in paths and generated object names. Domain/workload roles, warehouses, query tags and environment boundaries are better cost/ownership controls than creating a database for every source.

## RAW contract authoring

RAW contracts are reviewed engineering declarations, not source-discovery output. The Framework does not infer business keys, timestamps/order, CDC/delete semantics, capture fidelity or SCD pattern.

```bash
esf add-source fleet_mssql --project-root .
esf raw-contract-draft customer --source fleet_mssql --project-root .
# resolve every TODO
esf raw-contract-finalize customer --source fleet_mssql --project-root .
esf add-dataset customer --source fleet_mssql --pattern scd2 --project-root .
esf plan --source fleet_mssql --project-root .
esf scaffold-preview customer --source fleet_mssql --project-root .
esf scaffold scd2 customer --source fleet_mssql --project-root .
```

Incomplete drafts live under `contracts/drafts/`; reviewed contracts live under `contracts/raw/`. See `docs/architecture/RAW_CONTRACT_AUTHORING.md`.

## Logical pattern vs execution model

```text
pattern
  append | full_refresh | scd1 | scd2 | custom

execution_model
  stream_task | dynamic_table | batch_sql | custom
```

Supported combinations deliberately fail closed outside this matrix:

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

`procedure` is an implementation artifact, not an execution model. See `docs/architecture/EXECUTION_MODELS.md`.

## Generated-once ownership

A standard Stream/Task version typically owns explicit files such as `version.yml`, object DDL, apply/replay/validation SQL, Task DDL, registration/publication SQL and a deploy-manifest fragment. Dynamic Table versions intentionally omit fake Stream/Task/apply/replay artifacts.

```text
NOT EXISTS -> create requested ownership unit
EXISTS     -> DOMAIN OWNED FOREVER
```

There is deliberately no scaffold `--force`. Framework upgrades may add project-level migrations, tools or runbooks, but do not rewrite existing domain-owned dataset versions.

## Version-local Stream/Task policy — 0.23

Task execution policy belongs to `version.yml`, not the logical source manifest or SLA:

```text
warehouse                        -> WAREHOUSE
minimum_trigger_interval_seconds -> USER_TASK_MINIMUM_TRIGGER_INTERVAL_IN_SECONDS
timeout_seconds                  -> USER_TASK_TIMEOUT_MS
suspend_after_failures           -> SUSPEND_TASK_AFTER_NUM_FAILURES
error_integration                -> ERROR_INTEGRATION
```

Optional settings are omitted when unspecified. The Framework does not expose arbitrary schedules, generic `AFTER` graphs, generic retry orchestration or a universal readiness DSL. See `docs/architecture/TASK_OPERATIONAL_CONFIG.md`.

## Domain-local Control Plane

Each domain owns writable `CONTROL`. Enterprise monitoring consumes stable read-only exports rather than writing into one shared enterprise runtime-control database.

A fresh 0.25 project contains these ordered Framework migrations:

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
130_health_evaluation_cadence.sql
140_dynamic_table_observability_enrichment.sql
```

Released numbered migrations are immutable. Never edit `001..140` in place after release; append a later migration.

Important later contracts:

```text
090_dataset_execution_model.sql
  -> version execution model and primary runtime identity

100_dynamic_table_observability.sql
  -> original Dynamic Table native observability boundary

110_pipeline_execution_metrics.sql
  -> canonical explicit-pipeline DML/query-id metrics

120_release_readiness.sql
  -> candidate/release readiness and release audit

130_health_evaluation_cadence.sql
  -> audited health evaluator cadence changes without editing 040

140_dynamic_table_observability_enrichment.sql
  -> richer Snowflake-native Dynamic Table diagnostics on the existing views
```

Rerunning `esf init-project` materializes newly introduced missing Framework files but never rewrites an existing domain-owned `control_plane/deploy_manifest.txt`. Use `esf control-plan --project-root .` and explicitly append adopted migrations without reordering recorded history.

## Canonical explicit-run metrics — 0.20

For explicit Silver apply procedures:

```text
ROWS_AFFECTED = SQLROWCOUNT for the primary Silver DML
DML_QUERY_ID  = SQLID captured immediately after that same DML
```

Pattern-specific physical work belongs in `METRICS`; historical `ROWS_INSERTED / ROWS_UPDATED / ROWS_DELETED` are compatibility evidence rather than one universal semantic contract. See `docs/architecture/RUN_EVIDENCE.md`.

## Dynamic Table observability — 0.25

Dynamic Table execution remains Snowflake-native. The Framework does **not** create fake `CONTROL.PIPELINE_RUN` rows.

The existing observability path is enriched, not replaced:

```text
INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY
INFORMATION_SCHEMA.DYNAMIC_TABLES
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V
  -> CONTROL.DATASET_OBSERVABILITY_V
  -> health / SLA / incidents
```

Migration `100_dynamic_table_observability.sql` is released and unchanged. Migration `140_dynamic_table_observability_enrichment.sql` adds current native evidence such as:

```text
refresh action / trigger / reinitialization reason
state / code / message / query id
native refresh statistics
inputs with changed data
scheduling state / reason
target / mean / maximum lag
time above target lag / within-target ratio
latest data timestamp
last completed refresh state
executing refresh query id
```

Detailed/raw diagnostics stay in `CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V`. The unified dataset view exposes only compact fields useful for routine triage. A current executing query normalizes to `RUNNING` ahead of a previous completed state.

The normal health path remains database-local Information Schema. Long-retention Account Usage reporting can be added separately when a real reporting requirement exists. See `docs/architecture/DYNAMIC_TABLE_OBSERVABILITY.md`.

## Unified observability without unified runtime mechanics

```text
explicit Stream/Task or batch apply
  -> CONTROL.PIPELINE_RUN
  -> CONTROL.PIPELINE_EXECUTION_METRICS_V

Dynamic Table
  -> native Snowflake refresh/scheduling metadata
  -> CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V

both
  -> CONTROL.DATASET_OBSERVABILITY_V
  -> health / SLA / incidents
```

Do not introduce a second competing unified execution-health layer.

## Domain health evaluator cadence — 0.24

Released `040_health_task.sql` retains its historical one-minute schedule. Migration `130_health_evaluation_cadence.sql` creates audit/read surfaces but performs no `ALTER TASK`.

Cadence changes are explicit generated operations:

```bash
esf health-cadence-sql health-every-5m \
  --interval-seconds 300 \
  --reason "Reviewed domain health cadence" \
  --resume-after \
  --project-root .
```

The first contract supports 10..691200 second interval schedules and deliberately excludes cron. The operator explicitly chooses `--resume-after` or `--leave-suspended`. Partial operation failure leaves `STARTED` evidence and is not blindly retried. See `docs/architecture/HEALTH_EVALUATION_CADENCE.md`.

## Apply-once deployment

`control_plane/deploy_manifest.txt` and `silver_processing/deploy_manifest.txt` are ordered migration histories, not replay lists.

```text
contract validation
  -> control baseline preflight
  -> manifest validation
  -> Snowflake authentication
  -> bootstrap CONTROL.DEPLOYMENT_HISTORY
  -> esf-migrate deploy
       new path                         -> APPLY
       same applied path/checksum/order -> SKIP
       checksum/path/order drift        -> BLOCK
       unresolved STARTED/FAILED        -> BLOCK
  -> dbt debug/build
```

Failed/partial Snowflake DDL is never blindly retried because statements can commit independently. See `docs/architecture/APPLY_ONCE_MIGRATIONS.md`.

## Candidate versions, release and rollback — 0.21

Candidate implementations live under `silver_processing/<source>/<dataset>/versions/vN/`. Creating a new version changes zero bytes in the previous version.

The intended path is:

```text
candidate deploy
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

`BLOCKED` has no bypass. `REVIEW_REQUIRED` requires explicit operator acceptance and reason. Stable consumer views are replaced only at the explicit release/rollback boundary with `COPY GRANTS`.

## Template provenance and upgrade planning — 0.22+

New implementation versions carry deterministic provenance:

```yaml
version:
  provenance:
    framework_version: 0.25.0
    template_id: scd2_stream_task
    template_revision: 2
    template_digest: sha256:...
```

Run:

```bash
esf upgrade-plan --project-root .
```

It reports `CURRENT`, `UPDATE_AVAILABLE`, `ADVISORY`, `UNKNOWN` or `UNVERIFIED` without editing domain-owned files. Pre-provenance versions remain `UNKNOWN`; the Framework never reverse-engineers old SQL to guess template history. See `docs/architecture/TEMPLATE_PROVENANCE.md`.

0.25 changes only project-level Control migration content, so dataset template revisions do not advance.

## Data quality, reconciliation and SLA

Generated structural validation writes version-local `CONTROL.DQ_RESULT`. Domain/source-specific reconciliation can write normalized `CONTROL.RECONCILIATION_RESULT`; business reconciliation logic is never inferred.

SLA belongs to the logical dataset. Execution settings such as Dynamic Table target lag, version Task timing and domain health evaluator cadence are not automatically converted into SLA thresholds.

## Enterprise monitoring

Each domain exposes stable read-only contracts such as:

```text
CONTROL.ENTERPRISE_HEALTH_EXPORT_V
CONTROL.DOMAIN_HEALTH_SUMMARY_V
```

Enterprise monitoring may aggregate those surfaces; writable operational state remains domain-local.

## dbt / Gold / Semantic

dbt starts from trusted Silver and owns downstream Gold/Mart/Semantic transformation. It is desired-state and may run every deployment after CONTROL/SILVER migrations. It is deliberately not the Bronze-to-Silver execution engine.

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

esf health-cadence-sql health-every-5m \
  --interval-seconds 300 \
  --reason "Reviewed domain health cadence" \
  --resume-after \
  --project-root .

esf lifecycle-sql customer pause_incident_123 \
  --source fleet_mssql --action pause --version v1 --project-root .

esf repair-plan customer --source fleet_mssql --problem silver --project-root .
esf repair-sql customer v2 --source fleet_mssql --project-root .
esf release-sql customer --source fleet_mssql \
  --from-version v1 --to-version v2 --project-root .

esf validate --project-root .
```

## Certification boundary

Credential-free CI validates package installation, released migration immutability, reference projects, dbt parse, unit/contracts and runtime-indirection guardrails.

A Framework SHA is **Snowflake-certified only** when the trusted certification workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA. Green static CI or a skipped trusted workflow is not live Snowflake acceptance.

## Roadmap state

The planned architecture roadmap through Framework 0.25 is complete. Further framework work should be driven by live Snowflake certification/integration evidence, a real domain adoption defect, or a concrete operational requirement—not by adding speculative abstraction.

## Deliberately absent

The toolkit does not contain a universal source-discovery engine, universal ingestion orchestrator, central generic SCD runtime, runtime metadata routing, deployment-time scaffolding, connector checkpoint ownership, executable generic DQ rules, automatic reconciliation/business-key/SCD/SLA inference, arbitrary Task orchestration DSL, fake Dynamic Table run ledgers, automatic production repair, automatic migration retry after partial DDL failure, or automatic business Mart/KPI/Semantic generation.
