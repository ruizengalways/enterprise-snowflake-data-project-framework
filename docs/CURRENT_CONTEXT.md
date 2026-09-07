# Current Context

Concise handoff for a new conversation. Read this before cross-repository changes.

## Active framework stack

```text
PR #2  feature/metadata-driven-scd2-contract
  -> PR #3  feature/bootstrap-handoff-contract
      -> PR #4  feature/medallion-config-snapshot-contract
          -> PR #5  feature/dataset-reset-generation
```

Current reset-aware immutable framework pin:

```text
8afe208bd911a59b9334add78a53878ffea93087
Framework CI #181: SUCCESS
```

PR #5 is intentionally stacked on PR #4. Retarget each PR after the lower stack merges.

## Current machine/runtime contract

```text
Medallion layers
  BRONZE
  SILVER_STAGING
  SILVER_INTERMEDIATE
  SILVER_CANONICAL
  GOLD_MARTS
  GOLD_SEMANTIC
  DQ

load strategies
  full_refresh
  append_only
  incremental_merge
  scd1_merge
  scd2_snapshot
  scd2_merge
  scd2_stream_task
```

Capture semantics remain independent from target/history semantics. Strategy-specific metadata stays typed and bounded; genuine source/domain-specific behavior remains explicit code.

## Dataset configuration control

Git is the configuration source of truth.

Validated dataset + RAW technical metadata is rendered as deterministic canonical JSON and SHA-256 under `esf_dataset_snapshots`. Runtime fields such as run ID, PR number and query tag are excluded from the hash.

Snowflake receives deployment audit only through domain-scoped platform APIs:

```text
PLATFORM_CONTROL.CONFIG.<DOMAIN>_DATASET_CONFIG_SNAPSHOT
PLATFORM_CONTROL.CONFIG.<DOMAIN>_REGISTER_DATASET_CONFIG_SNAPSHOT
```

Framework code must not directly DML the shared base table.

## Full reset contract

Full reset is intentionally different from repair/replay.

Framework PR #5 adds:

```text
esf_domain_reset_relation
esf_domain_reset_procedure
esf_domain_reset_start_call_sql
esf_domain_reset_complete_call_sql
esf_dataset_full_reset_sql
esf_execute_dataset_full_reset
```

The framework owns only the bounded lifecycle calls and execution sequence:

```text
RESET_START
  -> explicit domain cleanup relations
  -> RESET_COMPLETE
```

The domain repository owns the actual reconstructable relation list. Do not add a generic YAML list that lets callers supply arbitrary tables at runtime.

The execution helper validates fully-qualified unquoted relation names before issuing `TRUNCATE TABLE IF EXISTS`. It uses the platform-generated domain owner-rights procedures for control state and does not directly DML shared PLATFORM_CONTROL tables.

Reset generation semantics live in platform-infra PR #3. A cleanup failure leaves the dataset `RESETTING`; rerunning the same reset ID is allowed only while that platform reset remains `RESETTING`. A completed reset ID is rejected by the platform before any cleanup can restart.

## Stable deployment contract

Reusable deployment order:

```text
verify project SHA is reachable from main
  -> verify exact immutable framework pin
  -> validate project/RAW metadata
  -> derive database/warehouse/SILVER_STAGING context
  -> build bounded dbt vars + config snapshots
  -> protected GitHub Environment WIF
  -> dbt build
  -> only on success register all dataset config snapshots
```

A failed build is never recorded as a successful deployed configuration. Domain repositories keep only a thin environment-selection wrapper and must not copy OIDC/token logic.

### One-click versus promotion

The current browser wrapper is a one-click deployment of the ref selected for `workflow_dispatch` (normally current `main`). It is not yet a complete same-SHA cross-environment promotion orchestrator.

The architectural target remains:

```text
same immutable project SHA
DEV -> UAT -> PROD
```

After live DEV is proven, add release/promotion orchestration that carries forward the exact deployed SHA through an immutable release ref or deployment record, without DEV/UAT/PROD source branches.

## Platform dependency

Platform-infra PR #3 implements the matching reset/generation control plane:

```text
feature/dataset-reset-generation
verified implementation head c20c09c0c5f51dff17ebc5fb3eec75c89c5ce5a2
Terraform CI #167: SUCCESS
Platform Control SQL CI #37: SUCCESS
```

It provides generation-aware runtime state, `DATASET_LIFECYCLE`, `DATASET_RESET`, domain reset views/procedures and `AR_<DOMAIN>_RECOVERY`.

The important retry rule is fail-closed:

```text
same reset_id + RESETTING
  -> retry allowed

same reset_id + READY_FOR_RELOAD/COMPLETED
  -> rejected before cleanup
```

Platform-infra PR #2 remains the lower dependency for Medallion schemas and CONFIG, and PR #1 remains the lower dependency for normal runtime/bootstrap surfaces.

## Domain consumers

Transport PR #4 reset integration:

```text
verified source/static head 649021fa5f84e580361e86d9bf8c66664e581a04
dbt Static CI #53: SUCCESS
```

`vehicle_status` has an explicit Bronze/Silver/Gold Mart cleanup plan plus an executable `transport_vehicle_status_full_reset` operation.

Health PR #3 reset integration:

```text
verified source/static head d33f92a928e3c9ca553a843c2c52c4952d86a13b
dbt Static CI #34: SUCCESS
```

`patient` has its own explicit cleanup plan plus `health_patient_full_reset`.

Both domain PR Workspace workflows are still blocked at `Load approved Snowflake environment configuration` before Snowflake execution because real `ci` WIF configuration is not available.

## Proof boundary

Static CI proves metadata validation, deterministic config hashes, dbt offline parse/render, Medallion workspace naming, SCD2 behavior contracts, reset SQL rendering/execution helper structure, domain-scoped PLATFORM_CONTROL calls and deployment-workflow/wrapper guards.

Static CI does not prove real WIF authentication, live recovery-role grants, Snowflake `TRUNCATE`, cross-domain denial, generation rollover in a real account, real source snapshot/CDC consistency, retry/recovery, or performance.

## Next live gate

```text
merge/rebase stacked PRs in dependency order
  -> bootstrap Snowflake DEV + GitHub WIF
  -> deploy + verify PLATFORM_CONTROL
  -> one-click deploy one current-main domain revision to DEV
  -> verify config snapshot audit
  -> verify normal runtime + bootstrap fail-closed behavior
  -> grant/use one domain Recovery role
  -> execute one full reset
  -> prove old generation audit retention + new generation zero-state
  -> run main pipeline and prove lifecycle returns ACTIVE
  -> prove completed reset ID reuse fails before cleanup
  -> connect one real/deterministic external-style source
  -> prove snapshot -> incremental/CDC handoff and recovery
  -> then add exact same-SHA UAT/PROD promotion orchestration
```

Do not start Kafka Connector / direct Snowpipe Streaming / Openflow comparison work before that live foundation is proven.
