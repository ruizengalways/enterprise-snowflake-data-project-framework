# Backfill

Backfill means required historical data is missing from the platform and must be recovered from the source or another approved historical source.

Typical flow:

```text
Source / approved archive
  -> repair ingestion
  -> Bronze
  -> replay affected Silver
  -> rebuild affected dbt descendants
```

Backfill is connector/source-specific. Openflow, Snowpipe, Kafka connectors, API workers and external ETL tools each have different recovery controls, so this framework does not implement one universal backfill engine.

Every executed backfill should be represented in the domain `CONTROL.REPAIR_RUN` ledger and followed by reconciliation/health validation.
