# Domain decommission runbook

A business domain can be decommissioned independently because its repository, Snowflake database and `CONTROL` schema are domain-owned.

Do not start with destructive drops. Use staged decommission so consumers, audit evidence and rollback needs are understood first.

## Phase 1 — freeze and inventory

1. Stop accepting new datasets/features.
2. Inventory sources, ingestion integrations, Streams, Tasks, procedures, Silver published objects, dbt models, shares and downstream consumers.
3. Export the domain health/incident/open-repair state for the decommission record.
4. Identify regulatory, audit and rollback retention requirements.

## Phase 2 — stop data movement

Pause/disable ingestion in the system that owns it: Openflow, Snowpipe, Kafka connector, Talend/ADF, API worker or other orchestrator.

For framework-managed Snowflake dataset pipelines, generate and review dataset soft-decommission SQL with `esf lifecycle-sql ... --action decommission`.

Do not delete Bronze/Silver history at this stage.

## Phase 3 — consumer cutover

1. Confirm dashboards, shares, semantic models and downstream domains have migrated or been retired.
2. Revoke new write paths and scheduled execution.
3. Keep stable published views available during the agreed rollback/read-only window if required.

## Phase 4 — retention window

Keep the required Bronze/Silver/control audit evidence for the agreed period. Monitor for unexpected consumers and document any approved exceptions.

## Phase 5 — physical cleanup

Physical cleanup is a separate reviewed change. Depending on policy it may include dropping Tasks/Streams/procedures, published views, Silver/Bronze objects, stages/integrations, roles/warehouses and finally the domain database/repository.

The Framework does not generate a one-click destructive domain teardown. Infrastructure-owned resources must be removed through the infrastructure repository/tooling that created them.

## Final evidence

Record:

- decommission owner and approval
- effective date
- final repository commit
- final Snowflake object inventory
- retained/exported audit locations
- downstream migration confirmation
- infrastructure cleanup reference
- repository archive/removal decision
