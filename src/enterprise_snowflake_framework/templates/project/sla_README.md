# SLA policy revisions

This directory holds explicit, reviewable SQL that changes logical-dataset SLA policy.

Use `esf sla-sql` to generate a new policy revision file. The command never connects to Snowflake and never executes the generated SQL.

Examples:

```bash
esf sla-sql customer end_to_end_v1 \
  --source fleet_mssql \
  --stage END_TO_END \
  --cadence CONTINUOUS \
  --max-freshness-seconds 600

esf sla-sql vehicle_type daily_0400_v1 \
  --source reference_api \
  --stage END_TO_END \
  --cadence SCHEDULED_DEADLINE \
  --deadline-local-time 04:00:00 \
  --timezone Australia/Sydney
```

Policy files are domain-owned after generation. If a policy changes, create a new revision file rather than rewriting an already-reviewed historical script.

SLA policy is operational control for the logical dataset. It does not belong in source manifests and it does not determine which transformation runtime executes.
