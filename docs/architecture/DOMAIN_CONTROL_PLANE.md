# Domain control plane

## Decision

Each business domain owns its own operational control plane.

A transport domain, health domain and finance domain do not share one writable runtime control database. This keeps ownership, decommissioning, access control and operational blast radius aligned with the domain boundary.

The recommended shape is one `CONTROL` schema inside the domain database/account context used by the project.

```text
<DOMAIN_DATABASE>
  BRONZE
  SILVER
  GOLD
  CONTROL
```

A domain can therefore be retired by decommissioning its own database/control objects without coordinating changes to a central operational state store.

## Cross-domain observability

Enterprise-wide health is read-only aggregation.

Each domain publishes a stable dashboard-ready health view. An enterprise observability layer may union those views:

```text
TRANSPORT.CONTROL.DATASET_HEALTH_V
HEALTH.CONTROL.DATASET_HEALTH_V
FINANCE.CONTROL.DATASET_HEALTH_V
             |
             v
enterprise health dashboard / reporting layer
```

The aggregation layer does not route or execute domain pipelines.

## Core control tables

The first control-plane contract contains these concerns separately.

### DATASET

One row per logical dataset.

Recommended fields:

- dataset_id
- source_id
- dataset_name
- owner
- criticality
- pattern
- enabled
- bronze_relation
- published_silver_relation
- active_version
- candidate_version
- created_at
- updated_at

`enabled` represents operational state. It is not intended to be queried by a universal runtime router on every execution. Operational commands should suspend/resume the concrete Snowflake task and then record the resulting state.

### DATASET_VERSION

One row per implementation version.

Recommended statuses:

```text
DEVELOPMENT
DEPLOYED
BOOTSTRAPPING
SHADOW
VALIDATED
ACTIVE
RETIRED
FAILED
```

Record at least Git commit, deployed time, activation/retirement time and physical implementation relations.

### SLA_POLICY

Stores operational expectations independently from pipeline transformation logic.

Policies can be stage-specific:

- SOURCE_TO_BRONZE
- BRONZE_TO_SILVER
- SILVER_TO_GOLD
- END_TO_END

Supported cadence classes should include continuous/event-driven, interval-based and scheduled-deadline datasets.

### INGESTION_RUN

Normalizes evidence from whichever ingestion technology a project uses. The framework does not require every connector to run inside Snowflake; external run IDs can be recorded.

### PIPELINE_RUN

Records Bronze -> Silver execution evidence including dataset version, timestamps, row counts, task/query identity and failure details.

### DBT_RUN

Records downstream dbt execution evidence needed for dataset health and repair traceability.

### DATASET_HEALTH

A materialized current-state record per dataset for fast dashboard queries.

### INCIDENT

Tracks an ongoing operational problem through OPEN -> RESOLVED rather than creating a new incident on every health evaluation.

### REPAIR_RUN

Audits repair activity without turning repair into an autonomous production executor.

### VERSION_VALIDATION

Stores candidate-versus-active comparisons used before cutover.

## Pattern-specific state

Do not force unrelated state into a generic table.

Examples:

- `API_CURSOR_STATE` for a domain-owned API ingestion worker
- `FULL_REFRESH_STATE` for snapshot-specific state

SCD2 should not automatically get a custom checkpoint table when Snowflake Streams already provide the required consumption offset.

## Central procedures inside a domain

Domain-local shared control procedures are allowed for control-plane concerns such as:

- health evaluation
- SLA evaluation
- incident lifecycle
- run logging
- version state transitions

They must not become generic business/SCD transformation engines.

## Separation from configuration

Git remains the source of truth for transformation implementation and static project contracts. The control plane records deployed/operational state and evidence.

This prevents a control table from becoming an undocumented parameter store that changes production transformation behavior outside code review.
