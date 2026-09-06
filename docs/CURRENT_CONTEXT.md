# Current Context

Concise handoff for a new conversation. Read this before cross-repository changes.

## Active framework stack

```text
PR #2  feature/metadata-driven-scd2-contract
  -> PR #3  feature/bootstrap-handoff-contract
      -> PR #4  feature/medallion-config-snapshot-contract
```

Current PR #4 head and domain pin:

```text
02e3fca78b453e8a39a1722ce96b15dfc98d7cf8
Framework CI #175: SUCCESS
Bootstrap Contract CI #7: SUCCESS
```

PR #4 is intentionally stacked on PR #3. Retarget each PR after the lower stack merges.

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

A failed build is never recorded as a successful deployed configuration.

Domain repositories should keep only a thin environment-selection wrapper and must not copy OIDC/token logic.

## Platform dependency

Platform-infra PR #2 implements the matching Medallion schemas and CONFIG control plane:

```text
PR #2 feature/medallion-dataset-control-plane
head a086401844d764dee1ef8e8053abe73855878b6e
Terraform CI: SUCCESS
Platform Control SQL CI: SUCCESS
```

Platform-infra PR #1 remains the lower dependency for domain-scoped runtime/bootstrap surfaces.

## Domain consumers

Transport PR #3 is stacked on its runtime/SCD2/bootstrap PRs and pins this framework SHA. Its Metadata CI and dbt Static CI are green. `vehicle_status` is the reference standard SCD2 consumer.

Health PR #2 is stacked on Health PR #1 and pins this framework SHA. Its `patient` reference is intentionally `scd1_merge`: the current RAW reference contract does not declare real business attributes suitable for SCD2 tracking, so Health does not fabricate tracked columns merely for symmetry.

Both domain PR Workspace workflows still require real Snowflake `ci` WIF configuration.

## Proof boundary

Static CI proves metadata validation, deterministic config hashes, dbt offline parse/render, Medallion workspace naming, SCD2 behavior contracts, domain-scoped PLATFORM_CONTROL calls and deployment-workflow ordering/guards.

Static CI does not prove real WIF authentication, live grants/cross-domain denial, Snowflake transaction/concurrency behavior, real source snapshot/CDC consistency, retry/recovery or performance.

## Next live gate

```text
merge/rebase stacked PRs in dependency order
  -> bootstrap Snowflake DEV + GitHub WIF
  -> deploy + verify PLATFORM_CONTROL
  -> one-click deploy one domain to DEV
  -> verify config snapshot audit
  -> verify normal runtime + bootstrap fail-closed behavior
  -> connect one real/deterministic external-style source
  -> prove snapshot -> incremental/CDC handoff and recovery
```

Do not start Kafka Connector / direct Snowpipe Streaming / Openflow comparison work before that live foundation is proven.
