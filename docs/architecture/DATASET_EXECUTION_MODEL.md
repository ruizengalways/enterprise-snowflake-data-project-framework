# Dataset execution model v2

The execution-policy boundary is the dataset/table, not the database.

```text
Metadata = HOW TO RUN
SQL      = WHAT THE DATA MEANS
```

A single domain database may contain full refresh, append-only, merge, SCD1, SCD2, Dynamic Table and custom datasets at the same time. There is no database-level refresh strategy.

## Three orthogonal axes

### Data semantics

```yaml
load:
  strategy: scd2
```

Allowed golden-path values:

```text
full_refresh
append_only
incremental_merge
scd1
scd2
custom
```

This says how data is maintained.

### Materialization

```yaml
materialization:
  type: table
```

Golden-path values are `table`, `view`, `dynamic_table`, `snapshot`, and `custom`. This says what Snowflake/dbt object is produced.

### Runtime

```yaml
runtime:
  mode: dbt
```

Runtime values are `dbt`, `snowflake_managed`, `task`, `stream_task`, `external`, and `custom`. This says who executes or refreshes the object.

These axes are deliberately independent. Combination names such as `scd2_merge`, `scd2_snapshot` and `scd2_stream_task` do not exist.

## Readable SQL stays primary

A dataset may use one small technical config call:

```sql
{{ enterprise_snowflake_framework.esf_apply_dataset_config('vehicle_status') }}

select
    vehicle_id,
    status,
    depot_id,
    route_id,
    source_updated_at,
    source_operation,
    source_sequence
from {{ ref('stg_vehicle_status') }}
```

The Framework configures technical behavior only. JOIN, CASE, FILTER, GROUP BY, windows and business expressions remain in domain SQL.

## Source contract is separate

Raw/source contract v2 describes source meaning and evidence fidelity:

```text
grain
business key
source timestamp
CDC operation/sequence
delete semantics
capture fidelity
ordering columns
idempotency key
```

It does not name or configure Openflow, Kafka, Snowpipe, Fivetran, ADF or any other connector. Connector checkpoint ownership is outside this Framework.

## SCD2

For `load.strategy: scd2`, `materialization.type: table`, the standard materialization maintains:

```text
<ENTITY>_HISTORY
<ENTITY>_HISTORY__ESF_EVENTS   technical landed-event ledger
```

On each run it identifies newly landed deterministic events, marks affected business keys, rebuilds complete history for those keys from retained landed evidence, and atomically replaces only those keys in the authoritative history. Replay is idempotent and late-arriving events repair the relevant history without rebuilding unrelated keys.

A normal `<ENTITY>_CURRENT` view filters `is_current = true` once for all current-state consumers.

## SCD1

SCD1 is current-state correctness. Domain SQL chooses the deterministic winning row for the processing window; the bounded materialization performs keyed upsert and tombstone delete mechanics.

## Dynamic Tables

Dynamic Table is a materialization/runtime capability, not a load strategy. Gold declarative derivations are the default place to consider it:

```yaml
materialization:
  type: dynamic_table
  target_lag: 5 minutes
  refresh_mode: adaptive
runtime:
  mode: snowflake_managed
```

The model remains normal SQL. Metadata never describes the `GROUP BY` or business join.

## Custom

`custom` is first-class on each axis. A custom dataset can still reuse query tags, observability, guarded control APIs, config snapshots, DQ, deployment and reset lifecycle without handing its business implementation to the Framework.
