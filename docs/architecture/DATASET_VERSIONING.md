# Dataset versioning and blue/green release

## Logical and physical names

Consumers should use stable published Silver names. Implementation versions stay behind that stable contract.

Example logical dataset:

```text
fleet_mssql.customer
```

Published object:

```text
SILVER.CUSTOMER_HISTORY
```

Candidate implementation objects may be versioned internally:

```text
SILVER_IMPL.CUSTOMER_V1_HISTORY
SILVER_IMPL.CUSTOMER_V2_HISTORY
```

The exact physical naming strategy is a domain implementation detail, but consumers should not need to know whether v1 or v2 is active.

## Default SCD2 model

The default SCD2 design is one physical history table containing all versions. Current-state access is represented by the active-row predicate, normally:

```sql
WHERE IS_ACTIVE = TRUE
```

A project may expose a stable current view for convenience:

```sql
CREATE VIEW SILVER.CUSTOMER_CURRENT AS
SELECT *
FROM SILVER.CUSTOMER_HISTORY
WHERE IS_ACTIVE = TRUE;
```

A project may choose a separately materialized current table when performance evidence justifies it, but the framework does not require that physical design.

## Candidate development

An active version must continue serving production while a candidate version is developed.

```text
                    BRONZE.CUSTOMER
                         |
                +--------+--------+
                |                 |
            V1 stream         V2 stream
                |                 |
            V1 task           V2 task
                |                 |
            V1 apply          V2 apply
                |                 |
           V1 history        V2 history
             ACTIVE             SHADOW
```

A candidate version may use an independent Snowflake Stream so its consumption progress cannot affect the active version.

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

`FAILED` can be entered from any deploy/test stage.

## Historical bootstrap

A candidate version is not validated merely because it processes new events successfully.

Release flow:

```text
DEPLOY
  -> BOOTSTRAP / historical replay
  -> CATCH UP
  -> SHADOW
  -> COMPARE
  -> VALIDATE
  -> ACTIVATE
```

The candidate must be built from replayable Bronze history or another explicitly approved source of historical truth.

## Version comparison

Candidate-versus-active validation may compare:

- business-key coverage
- current active-row uniqueness
- null keys
- history row count
- overlapping effective periods
- missing/gapped history where applicable
- selected aggregates
- selected column hashes
- sample differences
- freshness
- runtime
- cost

A successful SQL execution alone is not a release acceptance signal.

## Activation

Cutover should be lightweight because the candidate is already built and validated.

Possible implementation techniques include stable views/pointers, object rename/swap or other domain-specific object switching. The framework should expose a release abstraction without forcing every dataset into one physical technique.

The first implementation must not make activation an autonomous metadata-driven runtime router.

## Rollback

A recently retired implementation should remain available for a defined rollback window. Rollback should restore the stable published contract to a previously validated version without rebuilding the full history during the cutover itself.

## Decommissioning

Because control-plane state and physical implementation are domain-local, a dataset or whole domain can be retired without leaving mandatory runtime dependencies in a global control database.
