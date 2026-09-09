# Landed-data processing bootstrap handoff

Bootstrap in Framework v2 is not source extraction orchestration. It records the handoff between an initial set of **already-landed Bronze evidence** and steady-state downstream processing.

```text
ingestion lands Bronze snapshot/evidence
        |
        | ingestion ownership ends
        v
Framework bootstrap records landed boundary
        -> validate/reconcile landed snapshot
        -> commit processing handoff
        -> Silver processing continues after that boundary
```

The boundary value must be meaningful inside Snowflake landed data, such as a landed timestamp, batch identity, file identity, snapshot identity or event boundary. It must not be an MSSQL LSN, Kafka connector offset or API extraction cursor owned by the ingestion system.

Bootstrap state is accessed only through domain-scoped `PLATFORM_CONTROL` views/procedures. Reconciliation must complete before the handoff is committed. This state is operational control metadata; it does not describe connector implementation in dataset YAML.
