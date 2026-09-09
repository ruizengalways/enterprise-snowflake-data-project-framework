# Dataset lifecycle operations

Lifecycle changes are generated as explicit SQL and reviewed by engineers. The Framework never connects to Snowflake to pause, resume or decommission a dataset.

Examples:

```bash
esf lifecycle-sql customer pause_incident_123 \
  --source fleet_mssql \
  --action pause \
  --version v1

esf lifecycle-sql customer resume_incident_123 \
  --source fleet_mssql \
  --action resume \
  --version v1

esf lifecycle-sql customer decommission_2026q4 \
  --source fleet_mssql \
  --action decommission
```

Pause/resume require an explicit version so the Framework never guesses the active implementation from repository files.

Decommission is deliberately soft in phase 1: stop processing, disable the logical dataset and retire versions while preserving published data, history and control-plane audit evidence. Physical DROP/cleanup is a separate approved retention/governance change.
