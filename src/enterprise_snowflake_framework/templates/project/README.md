# __PROJECT_NAME__

This repository owns the production source for one Snowflake data domain.

```text
Source -> Ingestion -> BRONZE -> explicit domain-owned Snowflake SQL -> SILVER -> dbt -> GOLD -> SEMANTIC
```

The Enterprise Snowflake Framework may create starter source code, but once a dataset directory exists under `silver_processing/<source>/<dataset>/`, that directory belongs to this repository forever. Scaffold commands must never rewrite it.

Start with:

```bash
esf add-source <source_id> --project-root .
esf plan --source <source_id> --project-root .
esf scaffold-all --source <source_id> --project-root .
esf validate --project-root .
```
