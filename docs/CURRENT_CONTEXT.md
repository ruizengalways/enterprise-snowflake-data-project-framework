# Current context

## Released baseline

Current stable Framework baseline after PR #25:

```text
version = 0.18.0
main    = e578a1cde76a6dee2b5dfd41f07aa390d9b65c71
```

`Silver-first Toolkit CI` run #245 passed for that merge SHA. The first `Snowflake Framework Certification` workflow-run was created from that successful main CI and its credentialed job was skipped, which is the intended behavior while certification is not explicitly enabled/configured.

The certification layer is implemented, but no real Snowflake artifact has yet reported `CERTIFIED` for this SHA. Do not describe 0.18.0 as Snowflake-certified until that happens.

For new-conversation handoff, read `docs/NEXT_CHAT_HANDOFF.md` first.

## Framework position

This repository is a project-creation and operations toolkit for readable Enterprise Snowflake domain repositories. It is not a universal data runtime.

The framework owns safe project/source scaffolding, reviewed RAW/Silver contract validation, explicit pattern source-code generation, domain-local control-plane foundations and reusable CI/deployment/certification workflows. Existing ownership units are never overwritten by scaffolding.

## Domain boundary

One business domain is one domain repository and normally one domain Snowflake database per environment.

```text
enterprise-snowflake-transport-analytics
  -> DEV_TRANSPORT / UAT_TRANSPORT / PROD_TRANSPORT
```

A domain may contain many sources. Source boundaries are preserved in repository paths and new Snowflake object names. Existing domain-owned pipelines are never renamed automatically.

## RAW contract authoring

RAW contracts are reviewed engineering declarations. The Framework does not inspect source catalogs, profile sources, infer business keys, infer source timestamps/order, choose CDC/delete semantics or choose an SCD pattern.

Incomplete contract work lives outside the production contract boundary:

```text
contracts/drafts/<source>/<dataset>.yml
```

`esf raw-contract-draft` creates one TODO-rich draft and never overwrites it. `esf raw-contract-finalize` refuses unresolved TODO values, applies the canonical RAW schema/semantic validation, and moves the exact reviewed bytes into:

```text
contracts/raw/<source>/<dataset>.yml
```

Drafts are not scanned by `esf validate`. Finalization never overwrites an existing formal contract and does not add the dataset declaration or scaffold Silver. The intended sequence is:

```text
source evidence / judgement
  -> raw-contract-draft
  -> engineer edits/reviews
  -> raw-contract-finalize
  -> add-dataset
  -> plan / scaffold-preview / scaffold
```

Source profiling/discovery remains a future optional separate repository, not a dependency of this Framework.

## Ingestion

`ingestion/` is a source-specific integration boundary. Projects may use Openflow, Snowpipe, Kafka connectors, external ETL/orchestrators or project-specific API ingestion. The Framework does not implement a universal ingestion runtime or own mature connector checkpoints.

Control migration 060 provides optional BEGIN/COMPLETE/FAIL ingestion run-evidence procedures. They write `CONTROL.INGESTION_RUN`; they do not schedule or route ingestion.

## Bronze -> Silver

Preferred Snowflake-native shape:

```text
BRONZE -> Stream/readiness -> Task -> dataset-local SQL procedure -> SILVER
```

Standard patterns are append, full_refresh, scd1, scd2 and custom. Pattern algorithms are reused at scaffold time to generate explicit dataset-local source code. There is no central metadata-driven SCD runtime.

New standard dataset starters include explicit object/apply/replay/validation/task/register/publish SQL plus policy and deploy-manifest fragments. Generated apply procedures write RUNNING/SUCCESS/FAILED evidence to `CONTROL.PIPELINE_RUN`.

A normal generated Task executes the dataset-local apply procedure and then its dataset-local validation procedure. `020_validate.sql` is committed, version-specific source code; it is not interpreted from runtime rule metadata.

SCD1 current-state mutation is now ordering-aware when the reviewed RAW contract provides ordering evidence. A matched incoming event must be strictly newer than the stored row's ordering tuple before it may update or delete current state. Equal ordering is duplicate/no-op; an older late-arriving event cannot regress current state. This correctness guard was added in 0.18.0 after designing the real Snowflake certification fixtures.

## Apply-once deployment

CONTROL and SILVER manifests are ordered apply-once migration manifests, not files to replay in full on every deployment.

The reusable deployment flow is:

```text
immutable project Git SHA + immutable Framework SHA
  -> esf validate
  -> esf-control-preflight
  -> manifest path/file safety checks
  -> GitHub OIDC / Snowflake WIF
  -> bootstrap CONTROL.DEPLOYMENT_HISTORY
  -> esf-migrate deploy
       CONTROL new files -> APPLY
       CONTROL recorded identical files -> SKIP
       SILVER new files -> APPLY
       SILVER recorded identical files -> SKIP
       drift / partial state -> BLOCK
  -> dbt debug
  -> dbt build
```

`CONTROL.DEPLOYMENT_HISTORY` is environment-local and records migration path, exact-file SHA-256, manifest position, project/framework Git SHAs, attempt status/timestamps, errors, GitHub run ID and operator reason when applicable.

Once an environment records a migration as `SUCCEEDED`, `BASELINED` or `REMEDIATED`, its path, checksum and manifest position are immutable there. Removing/reordering an applied path or changing its bytes blocks deployment. Future changes append a new migration path or use a new dataset implementation version.

`STARTED` and `FAILED` block rather than retry automatically. Snowflake DDL can partially commit before a later statement in the same file fails; an engineer must inspect/repair partial state and may then explicitly record remediation with `esf-migrate resolve`. Resolve does not re-execute the failed file.

Existing populated domains cannot be safely inferred as fresh. If CONTROL/SILVER objects exist while deployment history is empty, normal migration deployment blocks. The engineer must check out/review the exact already-deployed project revision and use `esf-migrate baseline --confirm-existing-state-reviewed`; baseline records those manifest files/checksums as `BASELINED` and executes zero historical migration files. Fresh empty domains must use normal first deployment, not baseline.

The normal GitHub path serializes deployments per domain/environment with `cancel-in-progress: false`.

Framework-released numbered control migration templates are immutable after release. A later correction adds a later numbered migration instead of editing 001..080 in place. Framework CI enforces this on pull requests.

Manifest position, not filename sorting, is the environment history contract. If a domain has already appended its own migration and a later Framework migration is introduced, append the new Framework migration without reordering already-recorded entries even when the resulting numeric filenames are not visually sorted.

dbt deliberately remains desired-state and runs on every deployment. Release/repair/lifecycle/SLA operation scripts remain explicit engineer-run operations outside the normal migration runner.

See `docs/architecture/APPLY_ONCE_MIGRATIONS.md`.

## DDL and release safety

Apply-once migration history decides whether a committed file may execute; generated DDL still has its own safety contract.

New version-owned persistent tables, streams, views, procedures and tasks are create-only/fail-closed. An unexpected pre-existing object name is an ownership conflict rather than an idempotency condition.

Initial stable published views are create-only. Candidate deployment never changes stable consumer views. Explicit release/rollback is the only generated replacement boundary, using `CREATE OR REPLACE VIEW ... COPY GRANTS` so non-OWNERSHIP consumer privileges survive replacement.

For stream-based candidates, release starts candidate processing before publication, replaces stable views, updates CONTROL lifecycle/version evidence, and suspends the old task last. Snowflake DDL can partially commit, so partial release remains an inspect/rollback scenario rather than being presented as one transaction.

Procedure-scoped temporary working tables intentionally retain their invocation-local replacement semantics; this exception is not a persistent-object ownership loophole.

## Trusted Snowflake certification

0.18.0 includes a real Snowflake certification layer separate from ordinary PR CI.

Credential-free PR CI continues to run package installation, released-migration immutability guards, reference validation, dbt parse, unit/contract tests and runtime-indirection guards. It does not execute PR-head SQL using the certification identity.

The trusted certification path is:

```text
successful trusted main push CI
  -> optional Snowflake Framework Certification
  -> GitHub Environment: snowflake-certification
  -> account-scoped GitHub OIDC / Snowflake WIF
  -> dedicated CI_FRAMEWORK_CERT database
  -> transient CONTROL / BRONZE / SILVER schemas
  -> real generated SQL + assertions
  -> guarded cleanup
  -> snowflake-certification.json / .md
```

The runner hard-requires:

```text
SNOWFLAKE_USER      = SU_GITHUB_FRAMEWORK_CERT
SNOWFLAKE_ROLE      = AR_FRAMEWORK_CERT
SNOWFLAKE_WAREHOUSE = WH_FRAMEWORK_CERT_TRANSFORM
SNOWFLAKE_DATABASE  = CI_FRAMEWORK_CERT
```

Published-grant certification uses a separate probe role:

```text
AR_FRAMEWORK_CERT_READER
```

The canonical real-Snowflake matrix covers APPEND, SCD1, SCD2 and FULL_REFRESH; initial/duplicate/update/delete/reinsert/late/out-of-order events; direct apply/replay/validate; manual `EXECUTE TASK`; triggered Stream->Task behavior; DQ evidence; apply-once first/repeat/checksum-drift/failure-block behavior; SCD2 v2 bootstrap plus post-stream candidate catch-up; version comparison; grant-preserving cutover; and rollback.

Dynamic Table is deliberately `NOT_APPLICABLE` until a genuine Dynamic Table execution model exists.

A revision is only Snowflake-certified when the real workflow produces an artifact with `status = CERTIFIED` for that exact Framework SHA. A normal green PR/main CI is not enough.

The first workflow-run after merging 0.18.0 was created correctly from main CI but skipped before credentialed execution because live certification remains disabled/unconfigured. This demonstrates the intended opt-in boundary, not a certification pass.

See `docs/architecture/SNOWFLAKE_CERTIFICATION.md`, `certification/README.md`, and `docs/NEXT_CHAT_HANDOFF.md`.

## Data quality and reconciliation

Control migration 080 adds normalized evidence rather than a generic DQ engine:

```text
dataset-local validation SQL -> CONTROL.DQ_RESULT
reconciliation code           -> CONTROL.RECONCILIATION_RESULT
```

The Framework-generated structural DQ starters are intentionally narrow:

```text
append       -> duplicate idempotency key + NULL business key
scd1         -> duplicate business key + NULL business key
full_refresh -> duplicate business key + NULL business key
scd2         -> multiple active rows + NULL business key + overlapping periods
custom       -> domain-authored
```

Business DQ remains domain-owned after scaffold. Reconciliation is not inferred; the domain chooses the correct comparison for Source -> Bronze, Bronze -> Silver or other boundaries and records a normalized result through `CONTROL.RECORD_RECONCILIATION_RESULT` when useful.

Evidence status is fail-closed. Intended severity is `ERROR` or `WARN`; unknown severity is normalized to `ERROR`. Intended status is `PASS` or `FAIL`; unknown status is stored as `INVALID` and evaluated as a failure rather than silently treated as success.

DQ evidence is version-specific. Only the active implementation version contributes to production DQ health; candidate evidence is retained for shadow/release review. For reconciliation, version-specific active evidence is preferred over unversioned evidence for the same stage; versionless evidence remains appropriate for non-versioned boundaries such as Source -> Bronze.

`ERROR` failures contribute red health and automatic `DQ_FAILURE` / `RECONCILIATION_FAILURE` incidents. `WARN` failures contribute yellow health without creating an automatic failure incident. The quality-incident evaluator has its own serverless task, created suspended, so adopting migration 080 cannot replace or silently suspend an existing domain-health task.

## Domain-local control plane

Each domain owns its own `CONTROL` schema. Do not create one shared writable `PLATFORM_CONTROL` database across all domains.

The control plane includes dataset/version identity, lifecycle, SLA policy, ingestion/pipeline/dbt run evidence, DQ/reconciliation evidence, health, incidents, version validation, repair audit and deployment history.

Logical dataset lifecycle is explicit: `ACTIVE`, `PAUSED`, `DECOMMISSIONED`.

Control-plane upgrades remain explicit. Rerunning `init-project` creates newly introduced missing files without overwriting existing files or the domain-owned deploy manifest. `esf control-plan` reports repo/manifest gaps. `esf-control-preflight` fails deployment when the selected Framework baseline is incomplete. Fresh projects include migrations through `080_data_quality_reconciliation.sql`.

## Enterprise health export

Each domain evaluates its own health and exposes a stable read-only contract through:

```text
CONTROL.ENTERPRISE_HEALTH_EXPORT_V
CONTROL.DOMAIN_HEALTH_SUMMARY_V
```

After migration 080 the export includes lifecycle, stage status, DQ status, reconciliation status, SLA, latency, freshness, incident and overall-health fields. Enterprise monitoring does not rerun or reinterpret domain DQ/SLA logic.

A separate enterprise monitoring repository/database explicitly UNIONs participating domain views. It owns cross-domain presentation only; it does not write to domain `CONTROL` schemas. Cross-domain grants remain platform-infrastructure concerns.

Because migration 080 extends the stable export columns, participating domains should be upgraded coherently before a central `SELECT * UNION ALL` contract is changed. During staggered upgrades, explicitly select the shared column set in the central view.

Removing a domain means removing that domain's read branch/grant after the retention decision. Other domain control planes remain unchanged.

## Run evidence

```text
source-specific ingestion -> CONTROL.INGESTION_RUN
Silver apply procedure    -> CONTROL.PIPELINE_RUN
Silver validation         -> CONTROL.DQ_RESULT
dbt model result          -> CONTROL.DBT_RUN
reconciliation code       -> CONTROL.RECONCILIATION_RESULT
```

New dbt projects include an `on-run-end` macro. A model only participates in one logical dataset's Gold health when it explicitly declares `config.meta.esf_dataset_id`; cross-dataset business marts should normally remain unmapped. Existing domain repos are not silently opted into dbt logging because `init-project` never rewrites an existing `dbt_project.yml`.

## SCD2 default

The default SCD2 model is one physical history table per implementation version. Current state is `IS_ACTIVE = TRUE`, exposed through a version-local current view and stable published current view. A separate physical current table is optional when performance evidence justifies it.

## Versioning and blue/green

Candidate versions live under `silver_processing/<source>/<dataset>/versions/vN/` and own independent physical objects, Stream/Task where appropriate, apply/replay procedures and validation SQL. Creating v2 changes zero bytes in v1.

```text
scaffold -> deploy candidate migrations once -> bootstrap/replay -> catch up -> shadow -> validate -> compare -> release SQL -> explicit cutover
```

Candidate DQ evidence remains version-specific and must be reviewed together with version comparison evidence before release. `release-sql` generates activate/rollback SQL for review; `esf` never executes it and does not automatically approve a candidate.

An important consequence of apply-once deployment is that a later redeploy no longer re-executes v1 `050_publish.sql`, so an explicit v2 cutover is not silently undone by replaying old published-view DDL.

## SLA and observability

SLA belongs to the logical dataset, not to the source manifest or implementation version. Supported cadence types are `CONTINUOUS`, `INTERVAL` and `SCHEDULED_DEADLINE`. Latency and freshness are separate metrics. Stage policy can cover Source -> Bronze, Bronze -> Silver, Silver -> Gold and end-to-end freshness.

`CONTROL.EVALUATE_DOMAIN_HEALTH()` refreshes base timing/SLA health and automatic ingestion/pipeline/dbt/SLA incidents. `CONTROL.EVALUATE_QUALITY_INCIDENTS()` separately manages DQ/reconciliation failure incidents. Sustained conditions reuse an incident key; recovery resolves it. Both serverless tasks are created suspended.

## Dataset lifecycle

`esf lifecycle-sql` generates explicit pause/resume/soft-decommission SQL and never executes it. Pause/resume require an explicit implementation version. Soft decommission stops known implementation tasks, marks the logical dataset `DECOMMISSIONED`, retires versions and preserves Bronze/Silver/published/audit evidence. Physical cleanup is a separate approved retention/governance change.

## Repair

Repair starts from the latest known-good layer:

- Gold wrong / Silver correct -> rebuild dbt descendants.
- Silver wrong / Bronze correct -> build a candidate and replay Bronze.
- Bronze wrong -> repair ingestion first, then replay downstream.

Replay, backfill and reset remain distinct.

`repair-plan` is read-only. `repair-sql` generates candidate-only reviewable scripts for the four standard patterns:

```text
append       -> idempotent Bronze event replay
scd1         -> ordered current-state rebuild/merge
scd2         -> affected-key history rebuild
full_refresh -> complete current Bronze snapshot rebuild
custom       -> domain-authored
```

A new empty candidate should normally use a full bootstrap with no range bounds. Bounded replay assumes a correct candidate baseline outside the requested range. Full-refresh rejects time ranges. All standard replay procedures write `CONTROL.REPAIR_RUN` evidence. Active production is not changed until a separately generated and reviewed release.

DQ/reconciliation evidence helps identify whether Bronze, Silver or a boundary is wrong; it does not automatically execute repair.

## Gold / KPI / Semantic

These remain exploratory domain work. The Framework keeps skeletons/examples but does not auto-generate business marts, KPI SQL or semantic business models.

## Architectural guardrails

Continue to reject source-profiling/discovery inside this repo, deployment-time scaffolding, runtime metadata routing, metadata -> runtime transformation SQL generation, central generic SCD runtime engines, universal ingestion orchestration, connector offset/checkpoint ownership, generic executable DQ rules in CONTROL, naive universal reconciliation, shared writable cross-domain control planes, hidden active-version switching, automatic production repair execution, automatic failed-migration retry, automatic migration baseline inference, automatic business-key/SCD/SLA inference, destructive one-click decommission and automatic business Mart/KPI/Semantic generation.

The control plane may centralize operational health/version/incident/lifecycle/run-evidence/quality-evidence/deployment-history logic inside a domain, but must not hide dataset transformation or business-quality behavior.
