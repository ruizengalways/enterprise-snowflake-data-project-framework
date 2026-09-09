# Landed-data processing bootstrap handoff

Bootstrap is not source extraction orchestration. It records the handoff between an initial set of already-landed Bronze evidence and steady-state Silver processing.

```text
ingestion lands Bronze snapshot/evidence
        |
        | ingestion ownership ends
        v
PLATFORM_CONTROL records landed processing boundary
        -> validate/reconcile landed snapshot
        -> commit processing handoff
        -> explicit domain Silver SQL continues after that boundary
```

The boundary must be meaningful inside landed Snowflake data, such as a landed timestamp, batch identity, file identity, snapshot identity or event boundary. It must not be an MSSQL LSN, Kafka connector offset or API extraction cursor owned by ingestion.

Bootstrap state is accessed only through domain-scoped `PLATFORM_CONTROL` views/procedures. The toolkit may validate a domain contract or workflow, but it does not generate or execute the Silver business/state logic.
