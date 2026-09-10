# Ingestion run evidence

Ingestion remains source-specific. The Framework does not schedule Openflow, Snowpipe, Kafka, Talend, ADF, APIs or other connectors.

What the domain control plane does standardize is the **evidence contract** after an ingestion implementation has been chosen.

Use `CONTROL.INGESTION_RUN` so health/SLA dashboards can answer:

- did the latest ingestion succeed?
- what source event range did it cover?
- when was Bronze published?
- how many rows arrived?
- what external connector/job run produced it?

## Optional ledger API

Control migration `060_run_evidence_api.sql` provides three small procedures:

```sql
CALL CONTROL.BEGIN_INGESTION_RUN(...);
CALL CONTROL.COMPLETE_INGESTION_RUN(...);
CALL CONTROL.FAIL_INGESTION_RUN(...);
```

They only write the run ledger. They do not manage connector state or trigger Silver.

Use them when the ingestion technology can execute Snowflake SQL at job boundaries, for example a domain-owned API worker, Talend/ADF job, or an Openflow flow with an explicit completion step.

For managed ingestion where direct boundary callbacks are awkward, keep the connector authoritative and build a small domain-owned adapter/reconciliation task from the native operational history into `CONTROL.INGESTION_RUN`. Do not recreate Kafka offsets, Snowpipe file state, or managed CDC checkpoints in the Framework.

## Run identity

Generate a new run id for each ingestion attempt. Reusing the same id is treated idempotently by `BEGIN_INGESTION_RUN`; it does not create a second ledger row.

`EXTERNAL_RUN_ID` should contain the native job/flow/batch id when one exists. It is for traceability, not for runtime routing.

See `ingestion/examples/run_evidence.sql` for a copyable example.
