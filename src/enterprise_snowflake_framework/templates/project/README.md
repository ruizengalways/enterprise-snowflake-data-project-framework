# __PROJECT_NAME__

This repository owns the production source and operational control for one Snowflake data domain.

```text
Source -> Ingestion -> BRONZE -> Stream/readiness -> Task -> domain-owned SQL/procedure -> SILVER -> dbt -> GOLD -> SEMANTIC
```

The Enterprise Snowflake Framework may create starter source code, but once a dataset directory exists under `silver_processing/<source>/<dataset>/`, that directory belongs to this repository forever. Scaffold commands must never rewrite it.

This project also owns a domain-local control plane under:

```text
control_plane/
```

The committed SQL creates this domain's `CONTROL` schema, operational ledgers, health state and dashboard-ready views. It is not a shared global runtime database.

Start with:

```bash
esf add-source <source_id> --project-root .
esf plan --source <source_id> --project-root .
esf scaffold-all --source <source_id> --project-root .
esf validate --project-root .
```

Operational guidance lives under:

```text
operations/replay/
operations/backfill/
operations/reset/
```

Repair SQL should be generated/reviewed explicitly and executed by engineers. Project initialization never runs production repair automatically.
