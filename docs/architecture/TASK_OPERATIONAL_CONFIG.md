# Stream/Task operational configuration

This document describes the human-facing contract for Framework 0.23 Task execution policy. The machine-readable contract remains `src/enterprise_snowflake_framework/schemas/version.schema.json`; generated `version.yml` is the version-local declaration used by engineers and tooling.

## Boundary

Task settings are implementation-version execution policy. They are not logical dataset semantics, source metadata, or SLA policy.

```text
logical dataset
  pattern / RAW contract / SLA

implementation version
  execution_model = stream_task
  task operational policy
```

Do not move these fields into `config/sources/*.yml` and do not infer SLA from them.

## Supported configuration

A new `stream_task` implementation always declares the Task warehouse:

```yaml
version:
  execution_model: stream_task
  task:
    warehouse: WH_TRANSPORT_TRANSFORM
```

Optional settings are deliberately narrow:

```yaml
version:
  task:
    warehouse: WH_TRANSPORT_HEAVY
    minimum_trigger_interval_seconds: 60
    timeout_seconds: 900
    suspend_after_failures: 3
    error_integration: TASK_ERROR_NOTIFICATIONS
```

They map directly to Snowflake Task properties:

```text
warehouse                         -> WAREHOUSE
minimum_trigger_interval_seconds -> USER_TASK_MINIMUM_TRIGGER_INTERVAL_IN_SECONDS
timeout_seconds                  -> USER_TASK_TIMEOUT_MS
suspend_after_failures           -> SUSPEND_TASK_AFTER_NUM_FAILURES
error_integration                -> ERROR_INTEGRATION
```

`timeout_seconds` is converted to milliseconds only at SQL rendering time so the human declaration stays easy to read.

## Default policy

The Framework does not invent values for optional Task parameters. When an optional setting is absent, the generated `CREATE TASK` omits that property and Snowflake's own default remains in effect.

The warehouse continues to default to the domain transform warehouse because user-managed compute is already part of the generated Stream/Task execution model:

```text
WH_<PROJECT_CODE>_TRANSFORM
```

An engineer can override it per implementation version with `--warehouse`.

## Trigger interval scope

`minimum_trigger_interval_seconds` is accepted only for generated Task implementations that actually use a Stream readiness condition:

```text
append + stream_task
scd1   + stream_task
scd2   + stream_task
```

The accepted range is `10..604800` seconds, matching Snowflake's Task parameter contract.

`full_refresh + stream_task` has no generated Stream readiness signal. Its Task starter deliberately contains no `WHEN SYSTEM$STREAM_HAS_DATA(...)`, so `minimum_trigger_interval_seconds` is rejected instead of emitting a property whose intended readiness semantics are absent.

## Timeout and automatic suspension

`timeout_seconds` accepts `0..604800` seconds and renders as `USER_TASK_TIMEOUT_MS`.

`suspend_after_failures` accepts zero or greater and renders as `SUSPEND_TASK_AFTER_NUM_FAILURES`. Zero therefore remains an explicit Snowflake choice to disable automatic suspension after repeated user failures/timeouts.

These are runtime safety settings, not data freshness guarantees.

## Error integration

`error_integration` is optional and is rendered as `ERROR_INTEGRATION`. The first Framework contract accepts an unquoted Snowflake identifier only. This keeps generated SQL deterministic and avoids introducing quoted-identifier parsing rules into the scaffold layer.

The integration itself remains environment/platform infrastructure. The Framework references its name; it does not create or manage the notification integration.

## Deliberately excluded

0.23 does not expose:

```text
arbitrary SCHEDULE / cron configuration
generic AFTER task-graph wiring
TASK_AUTO_RETRY_ATTEMPTS abstraction
universal readiness DSL
general-purpose orchestration metadata
```

`TASK_AUTO_RETRY_ATTEMPTS` remains task-graph-root behavior in Snowflake and is not treated as a universal standalone dataset retry policy.

If later operational evidence requires graph orchestration, it should be designed as a separate explicit contract rather than gradually turning `version.yml` into an orchestration language.

## CLI

The same narrow options are available on `scaffold`, `scaffold-preview`, and `scaffold-version`:

```bash
esf scaffold-version customer v2 \
  --source fleet_mssql \
  --execution-model stream_task \
  --warehouse WH_TRANSPORT_HEAVY \
  --task-minimum-trigger-interval-seconds 60 \
  --task-timeout-seconds 900 \
  --task-suspend-after-failures 3 \
  --task-error-integration TASK_ERROR_NOTIFICATIONS \
  --project-root .
```

All validation happens before files are written. Existing dataset/version directories remain domain-owned and are never rewritten.

## Backward compatibility

Pre-0.23 `stream_task` versions may have no `task:` block. They remain valid and load with their historical generated Task SQL unchanged.

0.23 changes the generated Stream/Task artifact contract, so Stream/Task template provenance advances from revision 1 to revision 2. Revision 1 remains in the immutable template registry. `esf upgrade-plan` can therefore report a known older Stream/Task template as `UPDATE_AVAILABLE` without modifying it or pretending that an advisory exists.

## Ownership rule

Task operational configuration follows the same generated-once rule as every implementation version:

```text
new version -> Framework may generate Task policy and SQL
existing version -> domain owned; Framework changes zero bytes
```

Operational tuning of an already-applied implementation should be reviewed as domain-owned change. Framework upgrades do not silently retune production Tasks.
