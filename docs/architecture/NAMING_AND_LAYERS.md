# Naming and layer vocabulary

This document separates **logical architecture language** from **physical Snowflake schema names**. Keeping those two concepts distinct avoids documentation drift without forcing unnecessary object renames.

## Canonical logical layers

Use these terms when explaining the architecture conceptually:

```text
Bronze
Silver
Gold / Marts
Semantic
Control
```

`Control` is cross-cutting operational metadata/evidence, not a transformation medallion layer.

The Framework may describe the main data path as:

```text
source -> ingestion -> Bronze -> Silver -> Gold / Marts -> Semantic
                              \-> Control evidence/health
```

This is a communication model. It does not require every project to call itself a "medallion architecture" and it does not imply that all data movement uses one runtime technology.

## Default physical schemas

The default physical schema vocabulary inside one domain database is:

```text
BRONZE
SILVER
GOLD_MARTS
SEMANTIC
CONTROL
```

`GOLD_MARTS` is intentionally the physical default even though human-facing architecture prose may say "Gold / Marts". Do not bulk-rename `GOLD_MARTS` to `GOLD` merely to make prose and identifiers identical.

Each domain owns its writable `CONTROL` schema. Cross-domain monitoring consumes read-only exports; it does not move writable control state into a shared enterprise runtime database.

## Deprecated or negative examples

A term can appear in documentation while explaining what **not** to build. For example, a sentence such as "do not create a shared writable `PLATFORM_CONTROL`" is not evidence that `PLATFORM_CONTROL` is a supported architecture name.

Static documentation checks therefore validate positive canonical contracts rather than failing on every textual occurrence of a deprecated or rejected term.

## Source and domain boundaries

A business domain normally maps to a repository plus one domain database per environment. A domain can contain multiple source systems. Source identity remains explicit in repository paths and generated object names; it is not represented by creating a new Snowflake database for every source by default.

Example:

```text
enterprise-snowflake-transport-analytics
  DEV_TRANSPORT / UAT_TRANSPORT / PROD_TRANSPORT
    BRONZE
    SILVER
    GOLD_MARTS
    SEMANTIC
    CONTROL

  config/sources/fleet_mssql.yml
  config/sources/vehicle_api.yml
```

Cost attribution is primarily enforced with domain/workload roles, warehouses, query tags and account/environment boundaries rather than by treating every source system as a database boundary.
