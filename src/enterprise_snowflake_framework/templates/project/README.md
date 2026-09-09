# __PROJECT_NAME__

This repository owns production data-pipeline source code and operational control for one Snowflake business domain.

```text
Source -> Ingestion -> BRONZE -> Stream/readiness -> Task -> domain-owned SQL/procedure -> SILVER -> dbt -> GOLD -> SEMANTIC
```

A domain may contain many source systems. New generated Snowflake object names preserve the source boundary so same-named datasets from different sources do not collide by default.

The Enterprise Snowflake Framework creates starters, but ownership is append-only:

```text
missing ownership unit -> create
existing ownership unit -> never overwrite
```

This applies to dataset roots, candidate `versions/vN/` directories and generated repair/release directories.

This project owns a domain-local control plane under:

```text
control_plane/
```

The committed SQL creates this domain's `CONTROL` schema, operational ledgers, version/SLA state, health state and dashboard-ready views. It is not a shared global runtime database.

Start with:

```bash
esf add-source <source_id> --project-root .
esf plan --source <source_id> --project-root .
esf scaffold-preview <dataset> --source <source_id> --project-root .
esf scaffold-all --source <source_id> --project-root .
esf validate --project-root .
```

Candidate / repair / release flow:

```bash
esf scaffold-version <dataset> v2 --source <source_id> --project-root .
esf repair-plan <dataset> --source <source_id> --problem silver --project-root .
esf repair-sql <dataset> v2 --source <source_id> --project-root .
esf release-sql <dataset> --source <source_id> --from-version v1 --to-version v2 --project-root .
```

`repair-sql` and `release-sql` generate reviewable files only. They do not connect to Snowflake or execute production changes.
