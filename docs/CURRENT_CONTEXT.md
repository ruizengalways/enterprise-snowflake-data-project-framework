# Current context

This file describes the **current architecture**, not a chronological PR log. For a new conversation, read `docs/NEXT_CHAT_HANDOFF.md` first, then this file.

## Stable baseline

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
version    = 0.19.0
main       = a98a38bcb03b00a36c63cb0f2f8246d4356478d6
PR #27     = merged
PR CI #254 = SUCCESS
main CI #255 = SUCCESS
Snowflake Framework Certification run #11 = SKIPPED
```

The certification workflow skip is intentional while the trusted Snowflake environment is disabled/unconfigured. No 0.19.0 SHA has yet produced a real `status = CERTIFIED` artifact. Green static CI is not Snowflake certification.

## Framework position

This repository is a developer toolkit/bootstrapper for readable enterprise Snowflake domain repositories. It generates explicit source code, validates contracts and provides operational/deployment guardrails. It is **not** a universal runtime interpreter.

The framework deliberately does not own:

- source profiling/discovery;
- a universal ingestion engine;
- runtime metadata-to-SQL transformation routing;
- one central SCD engine;
- business DQ rule inference;
- autonomous production repair;
- Bronze-to-Silver execution through dbt.

Generated ownership units are created once, committed, reviewed and then domain-owned.

## Domain and repository boundary

One business domain normally owns one independent repository and one domain database per environment:

```text
enterprise-snowflake-transport-analytics
  -> DEV_TRANSPORT
  -> UAT_TRANSPORT
  -> PROD_TRANSPORT
```

A domain may contain many source systems. Source boundaries remain explicit under `config/sources`, `contracts/raw`, `ingestion` and `silver_processing`.

A typical domain database uses schemas such as:

```text
BRONZE
SILVER
GOLD_MARTS
SEMANTIC
CONTROL
```

Each domain owns its writable `CONTROL` schema. Do not replace this with one enterprise-wide writable `PLATFORM_CONTROL`.

## RAW contract authoring

RAW contracts are reviewed engineering declarations. The Framework never infers business keys, source timestamps, ordering, CDC/delete semantics or SCD pattern from source metadata.

Incomplete work belongs under:

```text
contracts/drafts/<source>/<dataset>.yml
```

The intended workflow is:

```text
source evidence / engineering judgement
  -> esf raw-contract-draft
  -> engineer edits/reviews all semantics
  -> esf raw-contract-finalize
  -> esf add-dataset
  -> esf plan
  -> esf scaffold-preview
  -> esf scaffold
```

`raw-contract-finalize` fails on unresolved TODOs, validates schema/semantics and never overwrites an existing formal RAW contract. It does not automatically declare or scaffold a dataset.

Source profiling/discovery remains a separate future capability/repository rather than a dependency of this Framework.

## Ingestion and Bronze

`ingestion/` is source-specific. A domain may use Openflow, Snowpipe, Kafka, APIs, ADF/Talend or other tools. The Framework does not own mature connector checkpoints or pretend all ingestion technologies share one runtime.

Bronze is the retained replay/audit evidence boundary.

Control migration 060 provides optional ingestion evidence procedures that write `CONTROL.INGESTION_RUN`; they do not schedule ingestion.

## Logical pattern vs execution model

0.19 separates dataset semantics from implementation technology.

Logical dataset pattern:

```text
append
full_refresh
scd1
scd2
custom
```

Version-specific execution model:

```text
stream_task
dynamic_table
batch_sql
custom
```

`pattern` remains in the source manifest and `CONTROL.DATASET`. `execution_model` belongs to `version.yml` and `CONTROL.DATASET_VERSION`.

`procedure` is not an execution model. It is an implementation artifact used by some models.

The supported 0.19 compatibility matrix is intentionally narrow:

```text
append       + stream_task   = supported
full_refresh + stream_task   = supported
full_refresh + dynamic_table = supported
full_refresh + batch_sql     = supported
scd1         + stream_task   = supported
scd1         + dynamic_table = supported
scd2         + stream_task   = supported
custom       + custom        = supported / domain-owned
```

All other combinations fail closed. In particular, `scd2 + dynamic_table` and `append + dynamic_table` are not supported merely because Snowflake can express related SQL constructs.

See `docs/architecture/EXECUTION_MODELS.md`.

## Stream + Task Silver

The historical/default standard implementation remains Snowflake-native Stream/readiness + Task + explicit dataset-local SQL/procedure.

Typical ownership unit:

```text
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

Apply procedures write `CONTROL.PIPELINE_RUN`. A generated Task runs apply and then dataset-local validation. New persistent version-owned objects are create-only/fail-closed.

SCD1 mutation uses reviewed ordering evidence. An incoming matched event must be strictly newer than the current row ordering tuple before update/delete. Equal tuples are duplicate/no-op; a late older event cannot regress current state.

SCD2 retains deterministic event evidence/history per implementation version and supports affected-key history rebuild for late-arriving evidence.

## Dynamic Table Silver

Dynamic Table is a first-class execution model for compatible declarative patterns.

A Dynamic Table version intentionally does **not** generate fake Stream, Task, apply or replay procedure files:

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

For `scd1 + dynamic_table`, current state is defined declaratively from Bronze using business key plus reviewed ordering columns and tombstone semantics.

For `full_refresh + dynamic_table`, the Dynamic Table represents the current Bronze snapshot.

Dynamic Table execution policy is version-local:

```text
target_lag
warehouse
refresh_mode = incremental | full
```

`TARGET_LAG` is a Snowflake staleness target, not a business SLA. `CONTROL.SLA_POLICY` remains separate. The Framework deliberately does not default Dynamic Tables to refresh mode `AUTO`.

Dataset-local Dynamic Table validation writes `CONTROL.DQ_RESULT` directly; the Framework does not fabricate a validation procedure/Task or fake `CONTROL.PIPELINE_RUN` entry.

## Batch SQL and custom

`batch_sql` is initially limited to `full_refresh`. It owns explicit batch transformation SQL/procedure artifacts but no Framework-owned scheduler. External scheduling remains explicit.

`custom` means the domain owns the execution behavior. The Framework provides minimal ownership/registration/publication authoring boundaries and does not invent a generic custom runtime.

## Version metadata and Control Plane

Fresh 0.19 projects include Control migrations:

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

Released numbered migrations are immutable. Future fixes append later migrations; do not edit 001..100 in place.

Migration 090 adds version execution metadata including:

```text
EXECUTION_MODEL
PRIMARY_RUNTIME_OBJECT
```

Legacy standard versions without an `execution_model` field remain readable as `stream_task`. Migration 090 backfills existing control rows from already-recorded implementation artifacts rather than choosing a new technology.

Migration 100 normalizes native Dynamic Table evidence through `INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY`. It creates `CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V` and upgrades `CONTROL.DATASET_OBSERVABILITY_V` so active Silver health reads the correct evidence source for the active execution model.

Dynamic Table refreshes are not represented by fake `CONTROL.PIPELINE_RUN` rows.

## Apply-once deployment

CONTROL and SILVER manifests are apply-once migration histories, not lists to replay every deployment.

Normal deployment:

```text
immutable project Git SHA + Framework SHA
  -> esf validate
  -> esf-control-preflight
  -> path/file safety checks
  -> GitHub OIDC / Snowflake WIF
  -> bootstrap CONTROL.DEPLOYMENT_HISTORY
  -> esf-migrate deploy
       NEW                        -> APPLY
       recorded + same checksum   -> SKIP
       checksum/path/order drift  -> BLOCK
       STARTED/FAILED unresolved  -> BLOCK
  -> dbt debug
  -> dbt build
```

Deployment history stores file path, exact SHA-256 checksum, manifest position, project/framework Git SHA, attempt timestamps/status/error details and GitHub run identity.

Once `SUCCEEDED`, `BASELINED` or `REMEDIATED`, an environment's migration path/checksum/position is immutable.

Existing populated domains with empty deployment history must use explicit reviewed baseline adoption. The Framework must never replay all historical SQL merely because the ledger is new.

Manifest order is environment history. Later Framework migrations are appended without reordering already-applied domain migrations.

Deployments are serialized per domain/environment. dbt remains desired-state and may run every deployment.

## DDL and publication safety

Apply-once history controls whether a file executes; the DDL itself also fails closed.

New version-owned persistent tables, streams, views, procedures, tasks and Dynamic Tables are create-only. Unexpected pre-existing names are ownership conflicts.

Initial stable published views are create-only. Candidate deployment never changes stable consumer objects.

Explicit release/rollback is the generated replacement boundary and uses:

```text
CREATE OR REPLACE VIEW ... COPY GRANTS
```

so explicit non-OWNERSHIP consumer grants survive stable-view switching.

Old processing is retired last so an earlier publication/control failure does not begin a cutover by stopping the currently active implementation.

Snowflake DDL is not treated as one rollbackable transaction; partial release requires state inspection and reviewed rollback/correction.

## Versioning, release and repair

Candidate implementations live under:

```text
silver_processing/<source>/<dataset>/versions/vN/
```

Creating a candidate changes zero bytes in the active implementation.

Typical flow:

```text
scaffold candidate
  -> append migrations
  -> deploy once
  -> bootstrap/replay/refresh as appropriate
  -> catch up
  -> DQ
  -> active-vs-candidate comparison
  -> explicit release SQL
  -> cutover
```

Release understands both old and new execution models. A supported example is:

```text
SCD1 v1 stream_task -> SCD1 v2 dynamic_table
```

A Dynamic Table candidate is refreshed before publication. A Stream+Task candidate may be activated according to its readiness model. Stable consumer views switch with `COPY GRANTS`; the old runtime is retired last.

Lifecycle is execution-model aware:

```text
stream_task   -> ALTER TASK SUSPEND / RESUME
dynamic_table -> ALTER DYNAMIC TABLE SUSPEND / RESUME
batch_sql     -> external scheduler coordination
custom        -> domain-authored
```

Repair starts from the nearest known-good layer. Dynamic Table repair uses explicit refresh/rebuild semantics rather than calling nonexistent replay procedures and rejects bounded replay where the execution model cannot represent it safely.

`repair-sql`, `release-sql`, `lifecycle-sql` and `sla-sql` generate reviewable operations and never execute production changes automatically.

## DQ and reconciliation

Control migration 080 provides normalized evidence rather than a generic DQ runtime:

```text
dataset-local validation -> CONTROL.DQ_RESULT
domain reconciliation   -> CONTROL.RECONCILIATION_RESULT
```

Framework-generated structural checks remain narrow. Business DQ and reconciliation logic are domain-owned.

Evidence is version-specific. Only the active implementation affects production DQ health; candidate evidence is retained for release review.

Unknown result status/severity fails closed. ERROR failures contribute red health and DQ/reconciliation incidents; WARN failures contribute yellow health without automatic failure incidents.

## SLA and health

SLA is logical-dataset policy, independent of source manifest and execution model. Supported cadence concepts include continuous, interval and scheduled-deadline evaluation across Source->Bronze, Bronze->Silver, Silver->Gold and end-to-end freshness.

Stream+Task Silver health uses `CONTROL.PIPELINE_RUN` evidence. Dynamic Table Silver health uses native refresh history normalized by migration 100.

Health and quality evaluator Tasks are serverless and created suspended. Adoption never silently resumes them.

## Enterprise monitoring

Each domain evaluates its own writable health state and exports stable read-only views:

```text
CONTROL.ENTERPRISE_HEALTH_EXPORT_V
CONTROL.DOMAIN_HEALTH_SUMMARY_V
```

Enterprise monitoring may UNION these exports but must not write back into domain CONTROL schemas or reinterpret domain SLA/DQ rules. Cross-domain grants belong in platform infrastructure.

## dbt / Gold / Semantic

dbt starts at trusted Silver. It is not a Silver execution engine.

New dbt projects include optional run-evidence integration. Only models explicitly mapped with `config.meta.esf_dataset_id` participate in one logical dataset's Gold health; cross-dataset marts should normally remain unmapped.

Gold marts, KPI semantics and business semantic views remain domain work and are not inferred by the Framework.

## Trusted real-Snowflake certification

The trusted certification layer is separate from untrusted PR CI.

Credential-free PR/main CI validates package installation, released-migration immutability, reference project structure, dbt parse, unit/contracts and runtime-indirection guardrails.

Full certification requires the dedicated Snowflake boundary:

```text
CI_FRAMEWORK_CERT
AR_FRAMEWORK_CERT
AR_FRAMEWORK_CERT_READER
SU_GITHUB_FRAMEWORK_CERT
WH_FRAMEWORK_CERT_TRANSFORM
```

Canonical live scenarios cover APPEND, SCD1, SCD2 and FULL_REFRESH behavior, Stream/Task execution, DQ, migration first/repeat/drift/failure behavior, candidate bootstrap/catch-up, grant-preserving cutover and rollback.

0.19 additionally includes a cross-execution-model certification scenario:

```text
SCD1 v1 stream_task
  -> v2 dynamic_table
  -> native refresh
  -> late/out-of-order equivalence
  -> post-candidate Bronze catch-up
  -> native refresh-history evidence
  -> DQ + comparison
  -> COPY GRANTS cutover
  -> execution-model-aware health
  -> rollback
```

A Framework revision is Snowflake-certified only when the trusted workflow emits `snowflake-certification.json` with `status = CERTIFIED` for that exact SHA.

For current 0.19.0 main, certification run #11 was safely skipped because live certification is not enabled/configured. Therefore 0.19.0 is **not yet Snowflake-certified**.

See `docs/architecture/SNOWFLAKE_CERTIFICATION.md` and `certification/README.md`.

## Immediate next priority

The highest-value next step is to configure/verify the dedicated Snowflake certification environment and run the real certification against exact main. Treat live Snowflake failures as product evidence rather than weakening canonical fixtures.

Only after live certification should the Framework add another large abstraction. A likely next feature is a release-readiness preflight that consumes existing candidate DQ, version-comparison and runtime evidence while leaving approval/cutover explicit and engineer-controlled.
