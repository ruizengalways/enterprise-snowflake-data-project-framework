# Operational control plane

The control plane standardizes operational state without becoming the data plane.

```text
DOMAIN DATA PLANE
BRONZE -> explicit domain Silver SQL/procedures -> SILVER -> dbt -> GOLD/SEMANTIC

DOMAIN CONTROL PLANE
logical dataset registry
version/release state
SLA policy
run evidence
health/incidents
repair audit
```

Each business domain owns its own `CONTROL` schema. There is no shared writable `PLATFORM_CONTROL` runtime database for all domains. This keeps operational ownership, access control and decommissioning aligned with the domain boundary.

Cross-domain observability is read-only aggregation of stable domain health views. A company-wide dashboard may union each domain's `CONTROL.DATASET_HEALTH_V`, but that aggregation layer does not route or execute pipelines.

RAW contracts describe accepted source evidence. `silver_processing/<source>/<dataset>/pipeline.yml` describes the small, reviewable contract for a domain-owned Silver implementation. Neither contract contains connector runtime state or dynamically generated production SQL.

Connector-specific state stays with the ingestion technology when the connector already owns it. Examples include SQL Server CDC LSNs and Kafka offsets. Domain-owned API workers may use a dedicated `CONTROL.API_CURSOR_STATE`. Full-refresh state, when required, belongs in a separate concern-specific table rather than a universal state table.

A Snowflake Stream can supply consumption offset for change-driven Bronze -> Silver pipelines, so SCD2 does not automatically require a custom checkpoint table.

Domain-local control procedures are allowed for health/SLA evaluation, incident lifecycle, run logging and version state management. They must not become central generic SCD/business transformation engines.

Transformation code remains reviewed in the domain repository. The control plane records deployed state and operational evidence; it is not an arbitrary parameter store for changing transformation semantics outside Git review.
