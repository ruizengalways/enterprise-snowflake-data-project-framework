# Domain health operations

This directory contains reviewed domain-level health evaluator operations. It is not dataset SLA configuration.

Framework migration `130_health_evaluation_cadence.sql` adds an audit contract for cadence changes without modifying the historical one-minute schedule from released migration 040.

Generate a cadence operation with an explicit final Task state:

```bash
esf health-cadence-sql health-every-5m \
  --interval-seconds 300 \
  --reason "Five-minute health evaluation is sufficient for this domain" \
  --resume-after \
  --project-root .
```

Or deliberately leave the evaluator suspended after changing its schedule:

```bash
esf health-cadence-sql health-every-15m-maintenance \
  --interval-seconds 900 \
  --reason "Prepare cadence before maintenance validation" \
  --leave-suspended \
  --project-root .
```

The generated operation directory is Framework-immutable after creation. Review preflight, operation and postflight SQL explicitly. If Task DDL fails after a `STARTED` audit row is written, inspect the partial state rather than blindly rerunning the same operation id.
