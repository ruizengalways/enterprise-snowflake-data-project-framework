# Dataset versioning and blue/green release

## Logical and physical names

Consumers use stable published Silver names. Implementation versions stay behind that stable contract.

For a new `fleet_mssql.customer` dataset, generated names preserve the source boundary:

```text
BRONZE.FLEET_MSSQL_CUSTOMER

SILVER.FLEET_MSSQL_CUSTOMER_V1_HISTORY
SILVER.FLEET_MSSQL_CUSTOMER_V1_CURRENT

published:
SILVER.FLEET_MSSQL_CUSTOMER_HISTORY
SILVER.FLEET_MSSQL_CUSTOMER_CURRENT
```

A second source can therefore also contain a `customer` dataset without colliding:

```text
SILVER.CRM_POSTGRES_CUSTOMER_CURRENT
```

Existing domain-owned object names are never rewritten by framework upgrades.

## Default SCD2 model

The default SCD2 design is one physical history table per implementation version containing all historical versions. Current-state access is:

```sql
WHERE IS_ACTIVE = TRUE
```

Each version also gets a version-local current view for shadow testing. Stable consumer views point at the active version.

A separately materialized current table is optional when performance evidence justifies it.

## Implementation ownership

The initial implementation lives at the dataset root:

```text
silver_processing/fleet_mssql/customer/
```

Candidate implementations live under independent ownership units:

```text
silver_processing/fleet_mssql/customer/versions/v2/
silver_processing/fleet_mssql/customer/versions/v3/
```

If a version directory already exists, `scaffold-version` changes zero bytes in it.

## Version-local execution objects

Each standard implementation version gets its own physical objects and execution path.

For SCD2 v2:

```text
BRONZE.FLEET_MSSQL_CUSTOMER_V2_STREAM
SILVER.FLEET_MSSQL_CUSTOMER_V2_EVENTS
SILVER.FLEET_MSSQL_CUSTOMER_V2_HISTORY
SILVER.FLEET_MSSQL_CUSTOMER_V2_CURRENT
SILVER.APPLY_FLEET_MSSQL_CUSTOMER_V2
SILVER.REPLAY_FLEET_MSSQL_CUSTOMER_V2
SILVER.FLEET_MSSQL_CUSTOMER_V2_TASK
```

V1 and V2 therefore consume the same Bronze source independently.

## Candidate lifecycle

Recommended lifecycle:

```text
DEVELOPMENT
  -> DEPLOYED
  -> BOOTSTRAPPING
  -> SHADOW
  -> VALIDATED
  -> ACTIVE
  -> RETIRED
```

`FAILED` may be entered from deploy/test stages.

Operational flow:

```text
scaffold-version v2
  -> deploy candidate SQL
  -> historical replay/bootstrap
  -> catch up stream
  -> shadow
  -> 020_validate.sql
  -> 025_compare.sql
  -> review CONTROL.VERSION_VALIDATION
  -> release-sql
  -> explicit activate.sql
```

A candidate is not accepted merely because its task ran successfully.

## Historical bootstrap

Create candidate objects before replay so the candidate Stream establishes its own offset. Replay can then rebuild retained historical evidence while new Bronze changes accumulate independently. After replay, run/catch up the candidate apply procedure. Idempotency defined by the RAW contract prevents replayed evidence from being duplicated when the stream later catches up.

This depends on Bronze retaining sufficient evidence. A source mode that only preserves current snapshots cannot reconstruct intermediate change history that never arrived in Bronze.

## Candidate validation

Every candidate gets:

```text
020_validate.sql
025_compare.sql
```

`020_validate.sql` validates the candidate itself. `025_compare.sql` compares stable active published data with the candidate and writes generic evidence to `CONTROL.VERSION_VALIDATION`.

Generic comparison includes, where applicable:

- current row count
- business-key coverage
- candidate business-key uniqueness
- SCD2 history row-count difference

History-count differences are marked for review rather than assumed to be failures because a corrected candidate may legitimately change history.

Domain engineers can add business-specific comparisons directly to `025_compare.sql` after scaffold; the file becomes domain-owned.

## Activation

`esf release-sql` generates a new review directory:

```text
operations/release/fleet_mssql/customer/v1_to_v2/
├── README.md
├── activate.sql
└── rollback.sql
```

The command does not connect to Snowflake and does not execute cutover.

The generated activation script:

1. suspends the old task;
2. repoints stable published view(s) to the candidate physical implementation;
3. updates `CONTROL.DATASET_VERSION` and `CONTROL.DATASET`;
4. resumes the new triggered task when the pattern has a Stream-based readiness model.

Full-refresh/custom readiness remains domain-specific and is not guessed by the release generator.

## Rollback

`rollback.sql` performs the inverse stable-view/control-state switch. A recently retired physical implementation should remain available for an approved rollback window. Rollback should not require rebuilding historical data during the cutover itself.

## Deployment manifests

Each implementation contains `deploy_manifest.fragment.txt`. It is a reviewable fragment showing the committed SQL that must be added to the domain-owned `silver_processing/deploy_manifest.txt` when the implementation is ready to deploy.

The framework does not edit an existing global deployment manifest behind the engineer's back and does not scaffold at deployment time.

## Decommissioning

Because data/control state is domain-local, a dataset or whole domain can be retired without mandatory runtime dependencies on a global writable control database. Enterprise-wide health aggregation should only consume stable read-only domain health surfaces.
