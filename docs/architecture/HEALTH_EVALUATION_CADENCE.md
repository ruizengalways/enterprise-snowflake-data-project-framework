# Domain health evaluation cadence

Framework 0.24 makes the schedule of `CONTROL.EVALUATE_DOMAIN_HEALTH_TASK` an explicit domain operational choice without changing the released migration that originally created the Task.

## Why migration 040 stays unchanged

Released `040_health_task.sql` created the serverless health evaluator with:

```sql
SCHEDULE = '1 MINUTE'
```

That file is already part of checksum-locked migration history. It is immutable. A configurable cadence therefore cannot be implemented by editing 040 or by regenerating existing domain SQL.

Framework 0.24 adds a later migration:

```text
130_health_evaluation_cadence.sql
```

Migration 130 creates an audit/read contract only. It deliberately performs **no `ALTER TASK`**. Merely upgrading the Framework therefore never retunes a running domain.

## Domain-level policy, not SLA

The health evaluator periodically computes the current operational health surface. Its own execution frequency is not a dataset freshness target.

Keep these concepts separate:

```text
CONTROL.SLA_POLICY
  -> what freshness / latency a logical dataset is expected to meet

health evaluator cadence
  -> how often this domain recomputes health evidence and incident state
```

No cadence is inserted into `config/project.yml`, source manifests, or dataset version metadata. The change is an explicit operational operation so old and new domains use the same mechanism.

## Supported interval

The first contract supports Snowflake interval schedules only:

```text
10 .. 691200 seconds
```

That is 10 seconds through 8 days, matching Snowflake's interval Task schedule range. Arbitrary cron expressions are deliberately excluded from this Framework contract.

The CLI always renders the requested value as:

```sql
ALTER TASK CONTROL.EVALUATE_DOMAIN_HEALTH_TASK
SET SCHEDULE = '<N> SECONDS';
```

Using seconds gives one canonical representation and avoids a second parser for equivalent minute/hour strings.

## Explicit state transition

Current Snowflake Task modification semantics require a standalone Task to be suspended before its properties are changed. The generated operation therefore always does:

```text
write STARTED audit evidence
  -> SUSPEND
  -> SET SCHEDULE
  -> optionally RESUME, only when explicitly requested
  -> mark audit SUCCEEDED
```

The operator must choose one final-state flag:

```text
--resume-after
--leave-suspended
```

The Framework never guesses whether a previously suspended Task should be resumed. Changing or resuming an interval schedule also re-anchors Snowflake's interval base time, so that state transition is operationally meaningful.

## Audit contract

Migration 130 creates:

```text
CONTROL.HEALTH_EVALUATION_CHANGE
CONTROL.HEALTH_EVALUATION_CONFIG_V
```

`HEALTH_EVALUATION_CHANGE` records Framework-generated attempts with operation id, requested interval, requested final state, reason, operator and timestamps.

`HEALTH_EVALUATION_CONFIG_V` exposes the latest **recorded successful Framework operation**. It is not claimed to be an authoritative reflection of out-of-band Snowflake edits. `SHOW TASKS` remains the direct verification surface for actual Task schedule/state.

A generated operation inserts `STARTED` before Task DDL. If later DDL fails, that incomplete row is intentionally left behind. The same operation id then fails closed. Inspect the Task and partial state before generating a new reviewed correction.

## CLI workflow

First materialize and adopt migration 130 using the normal apply-once process:

```bash
esf init-project --project-root .
esf control-plan --project-root .
# review and append 130 to the domain-owned deploy manifest when adopting it
# deploy the migration through the normal checksum-locked workflow
```

Then generate a reviewed operation:

```bash
esf health-cadence-sql health-every-5m \
  --interval-seconds 300 \
  --reason "Five-minute health evaluation is appropriate for this domain" \
  --resume-after \
  --project-root .
```

The Framework creates:

```text
operations/health/health-every-5m/
  README.md
  preflight.sql
  operation.sql
  postflight.sql
```

`esf` never executes these files. Preflight and postflight both expose `SHOW TASKS` so the engineer can compare recorded intent with the actual Snowflake Task.

## Ownership and upgrade behavior

The operation directory is generated once and then domain-owned. Calling the generator again with the same operation id changes zero bytes.

For an older domain, rerunning `esf init-project` can materialize the missing 130 migration and `operations/health/README.md`, but it does not edit the existing domain-owned `control_plane/deploy_manifest.txt`. `esf control-plan` reports 130 as missing from the manifest until the engineer explicitly adopts it.

This preserves all existing apply-once and generated-once rules while making the health evaluator cadence configurable.
