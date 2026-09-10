# Next chat handoff

Read this file first when continuing the Framework in a new conversation. Then read `docs/CURRENT_CONTEXT.md` and the architecture document most relevant to the next task.

## Stable repository state

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.19.0
main       = a98a38bcb03b00a36c63cb0f2f8246d4356478d6
merged PR  = #27 feat: separate execution models and add Dynamic Table Silver
PR CI      = Silver-first Toolkit CI #254 = SUCCESS
main CI    = Silver-first Toolkit CI #255 = SUCCESS
Snowflake certification workflow run #11 = SKIPPED
```

The skip is intentional while the trusted Snowflake certification environment is not explicitly enabled/configured. **No 0.19.0 SHA has yet produced a real `status = CERTIFIED` Snowflake artifact.** Do not describe 0.19.0 as Snowflake-certified until that happens.

There should be no need to reopen or redesign PR #27. Its architecture is now the stable main contract.

## Core model

Dataset semantics and Snowflake execution technology are separate concepts:

```text
logical dataset
  pattern = semantic behavior

implementation version
  execution_model = Snowflake execution technology
```

Logical `pattern` values:

```text
append
full_refresh
scd1
scd2
custom
```

Version-level `execution_model` values:

```text
stream_task
dynamic_table
batch_sql
custom
```

Do not add `procedure` as a peer execution model. A procedure is an implementation artifact used by some execution models.

The source manifest remains semantic-only: it stores `pattern` and `raw_contract`. It does **not** store `execution_model`. New `version.yml` files explicitly store execution model. Legacy standard version files without that field remain readable as `stream_task`.

## Supported execution matrix in 0.19.0

```text
append       + stream_task   = supported
full_refresh + stream_task   = supported
full_refresh + dynamic_table = supported
full_refresh + batch_sql     = supported
scd1         + stream_task   = supported
scd1         + dynamic_table = supported
scd2         + stream_task   = supported
custom       + custom        = supported / domain-owned

append       + dynamic_table = rejected
scd2         + dynamic_table = rejected
other unimplemented combinations = rejected
```

Keep this fail-closed. Do not enable a new combination until its semantic behavior, operations and real Snowflake certification are implemented.

## Dynamic Table implementation

Dynamic Table is now a first-class Bronze-to-Silver execution option for compatible declarative patterns. dbt still begins at trusted Silver; dbt is not a Bronze-to-Silver engine.

For SCD1 Dynamic Tables, current state is defined declaratively from reviewed Bronze evidence using business key plus ordering columns. Late/out-of-order older events must not regress current state, and tombstones are filtered according to the RAW contract.

For full-refresh Dynamic Tables, the Dynamic Table represents the current Bronze snapshot.

A Dynamic Table implementation does not receive fake Stream/Task/apply/replay procedure files. Its ownership unit is intentionally smaller:

```text
README.md
version.yml
001_dynamic_table.sql
020_validate.sql
025_compare.sql
040_register.sql
050_publish.sql
060_policy.sql
deploy_manifest.fragment.txt
```

`020_validate.sql` remains explicit dataset-local DQ source code and writes normalized `CONTROL.DQ_RESULT` evidence. It is not a fake validation Task/procedure.

Dynamic Table execution configuration is version policy:

```text
target_lag
warehouse
refresh_mode = incremental | full
```

`TARGET_LAG` is not the logical business SLA. `CONTROL.SLA_POLICY` remains separate. The Framework deliberately does not generate refresh mode `AUTO` in 0.19.0.

Example candidate:

```bash
esf scaffold-version customer v2 \
  --source fleet_mssql \
  --execution-model dynamic_table \
  --target-lag "5 minutes" \
  --warehouse WH_TRANSPORT_TRANSFORM \
  --refresh-mode incremental
```

## Control Plane through 0.19.0

Fresh domain control manifest now includes:

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
```

Never edit already released 001..100 migration templates in place after this release. Future fixes append a later migration.

`090_dataset_execution_model.sql` adds version-level execution metadata such as:

```text
CONTROL.DATASET_VERSION.EXECUTION_MODEL
CONTROL.DATASET_VERSION.PRIMARY_RUNTIME_OBJECT
```

`100_dynamic_table_observability.sql` reads Snowflake-native `INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY` and normalizes Dynamic Table refresh evidence. It does **not** fabricate `CONTROL.PIPELINE_RUN` rows. `CONTROL.DATASET_OBSERVABILITY_V` selects the appropriate Silver evidence source using the active version execution model.

For an old domain, rerun `esf init-project` to materialize missing 090/100 files, review `esf control-plan`, then explicitly append them to the domain-owned manifest without reordering already applied entries. `esf-control-preflight` remains the deployment gate.

## Lifecycle / repair / release

Lifecycle is execution-model aware:

```text
stream_task   -> ALTER TASK ... SUSPEND / RESUME
dynamic_table -> ALTER DYNAMIC TABLE ... SUSPEND / RESUME
batch_sql     -> coordinate external scheduler explicitly
custom        -> domain-authored
```

Repair no longer assumes every candidate has a replay procedure or Task. A Dynamic Table repair uses explicit refresh/rebuild semantics and rejects bounded replay when that execution model cannot represent it safely.

Release can cross execution technologies. The main 0.19 reference scenario is:

```text
customer v1: pattern=scd1, execution_model=stream_task
customer v2: pattern=scd1, execution_model=dynamic_table
```

Candidate deployment never changes stable consumer objects. Explicit release/rollback continues to switch stable published views with `CREATE OR REPLACE VIEW ... COPY GRANTS`. Candidate readiness/refresh happens before publication and the old runtime is retired last.

## Stable deployment contract

CONTROL and SILVER deployment use environment-local apply-once migration history:

```text
new path                       -> APPLY
same applied path/checksum     -> SKIP
changed applied checksum       -> BLOCK
removed/reordered history      -> BLOCK
unresolved STARTED/FAILED      -> BLOCK
```

`CONTROL.DEPLOYMENT_HISTORY` stores path, SHA-256, manifest position, project/framework Git SHA, timestamps/status/error details and GitHub run metadata.

Existing populated domains require explicit reviewed baseline adoption; the migration runner must never replay historical manifests simply because deployment history is new.

New persistent version-owned objects are create-only/fail-closed. Stable consumer view replacement is limited to explicit release/rollback and uses `COPY GRANTS`.

## RAW / source / dbt boundaries

- RAW contract decisions remain human-reviewed.
- source profiling/discovery is outside this Framework.
- ingestion technology remains source-specific.
- Bronze is replay/audit evidence.
- Silver uses explicit Snowflake-native source code generated once and then domain-owned.
- no universal runtime metadata routing or central SCD engine.
- dbt starts at trusted Silver and owns Gold/Mart/Semantic work.

## DQ, reconciliation and enterprise health

Dataset-local validation writes `CONTROL.DQ_RESULT`. Domain-authored reconciliation may write `CONTROL.RECONCILIATION_RESULT`. Active-version evidence affects production health; candidate evidence remains isolated for shadow/release review.

Each domain owns writable health/control state. Enterprise monitoring is read-only aggregation through:

```text
CONTROL.ENTERPRISE_HEALTH_EXPORT_V
CONTROL.DOMAIN_HEALTH_SUMMARY_V
```

Do not introduce one shared writable enterprise control plane.

## Trusted Snowflake certification

The certification layer is implemented and remains separated from untrusted PR CI. The trusted workflow requires the dedicated boundary:

```text
SNOWFLAKE_DATABASE  = CI_FRAMEWORK_CERT
SNOWFLAKE_ROLE      = AR_FRAMEWORK_CERT
SNOWFLAKE_USER      = SU_GITHUB_FRAMEWORK_CERT
SNOWFLAKE_WAREHOUSE = WH_FRAMEWORK_CERT_TRANSFORM
reader probe role   = AR_FRAMEWORK_CERT_READER
```

0.19 extends the live suite with:

```text
SCD1 v1 stream_task
  -> candidate v2 dynamic_table
  -> native refresh
  -> late/out-of-order equivalence
  -> post-candidate Bronze catch-up
  -> native refresh-history evidence
  -> DQ + version comparison
  -> COPY GRANTS cutover
  -> execution-model-aware health
  -> rollback
```

The exact main SHA is only Snowflake-certified when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED`. Static CI #255 is not that certification.

## Immediate next work

Start the next conversation with:

```text
Continue enterprise-snowflake framework.
First read docs/NEXT_CHAT_HANDOFF.md, docs/CURRENT_CONTEXT.md and docs/architecture/EXECUTION_MODELS.md.
Then re-check current main/open PR/CI before changing code.
```

Recommended next priority is **live Snowflake certification and acceptance**, not another large abstraction. Configure/verify the `snowflake-certification` GitHub Environment and dedicated Snowflake WIF/database/roles/warehouse, run the trusted certification from exact `main`, and treat live failures as product evidence.

After live certification, likely next work is a release-readiness gate that consumes existing candidate DQ/version comparison/runtime evidence without auto-approving or auto-cutting production.
