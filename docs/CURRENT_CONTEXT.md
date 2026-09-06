# Current Context

This file is the concise handoff for a new conversation. Read it before making cross-repository changes.

## Stable baseline

Framework `main` currently contains the merged domain-scoped operational API baseline. Active work is stacked because the SCD2 and bootstrap contracts have not all been merged to `main` yet.

Active stack:

```text
PR #2  feature/metadata-driven-scd2-contract
  -> PR #3  feature/bootstrap-handoff-contract
      -> PR #4  feature/medallion-config-snapshot-contract
```

PR #4 is the branch for the current database/control-plane/deployment work.

## What PR #4 adds

Machine/runtime changes:

```text
Medallion layer vocabulary
  BRONZE
  SILVER_STAGING
  SILVER_INTERMEDIATE
  SILVER_CANONICAL
  GOLD_MARTS
  GOLD_SEMANTIC
  DQ

explicit scd1_merge strategy
canonical JSON + SHA-256 dataset config snapshots
esf_dataset_snapshots dbt vars surface
PLATFORM_CONTROL.CONFIG domain-scoped read/register helpers
bulk config-snapshot registration macro
stable deployment context generated from validated Git metadata
config snapshot registration only after successful dbt build
```

Git remains the configuration source of truth. Snowflake CONFIG storage is an immutable deployment audit/readback ledger, not an editable parameter store.

## Stable deployment contract

The reusable deployment flow is:

```text
verify requested project SHA is reachable from main
  -> verify immutable framework pin
  -> validate project/RAW metadata
  -> resolve environment/domain database + warehouse + SILVER_STAGING default
  -> build bounded dbt vars and config snapshots
  -> authenticate with protected GitHub Environment WIF
  -> dbt build
  -> register all dataset config snapshots through domain-scoped owner-rights procedures
```

A failed build must not register the configuration as deployed.

Domain repositories should keep only a thin manual wrapper and should not copy OIDC/token logic.

## Platform dependency

The corresponding platform objects are implemented in `enterprise-snowflake-platform-infra` PR #2:

```text
feature/medallion-dataset-control-plane
PLATFORM_CONTROL.CONFIG.DATASET_CONFIG_SNAPSHOT
<DOMAIN>_DATASET_CONFIG_SNAPSHOT secure view
<DOMAIN>_REGISTER_DATASET_CONFIG_SNAPSHOT owner-rights procedure
```

Platform PR #2 also changes domain stable schemas to the Medallion vocabulary.

## Domain consumers

Transport currently has the stronger consumer stack because it already includes metadata-driven SCD2 + bootstrap handoff. Health is the second-domain operational-isolation proof.

After PR #4 is fully green, pin its immutable SHA into both domain repos and update their thin deployment wrappers to deploy the selected `main` revision with only an environment choice.

## Proof boundary

Static CI can prove:

```text
metadata schema/semantic validation
deterministic config hashes
dbt offline parse/render
Medallion workspace/target naming
SCD2 behavior oracle
no direct project DML on shared PLATFORM_CONTROL tables
reusable deployment workflow ordering and immutable-main guards
```

Static CI cannot prove:

```text
real Snowflake WIF authentication
real PLATFORM_CONTROL grants
cross-domain denial in Snowflake
transaction/concurrency behavior
source snapshot/CDC consistency
live retries/recovery/performance/credits
```

Do not describe the control plane as live-deployed until the DEV Snowflake account and GitHub Environment WIF variables exist and the live verification gate has run.

## Next gate

```text
finish PR #4 CI
  -> pin final framework SHA in Health + Transport
  -> make domain Deploy workflow environment-only
  -> add domain deployment/current-context docs
  -> update platform CURRENT_CONTEXT with new PRs/SHAs
  -> bootstrap DEV Snowflake + WIF
  -> deploy/verify PLATFORM_CONTROL
  -> one-click deploy one domain to DEV
  -> prove config snapshot audit + normal runtime + bootstrap fail-closed behavior
```
