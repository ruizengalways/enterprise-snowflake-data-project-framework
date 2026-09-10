# Enterprise health export

Each domain owns and evaluates its own operational health. Enterprise monitoring consumes a stable read-only export from every domain; it does not become a shared writable control plane.

```text
TRANSPORT.CONTROL -> ENTERPRISE_HEALTH_EXPORT_V
HEALTH.CONTROL    -> ENTERPRISE_HEALTH_EXPORT_V
FINANCE.CONTROL   -> ENTERPRISE_HEALTH_EXPORT_V
                         |
                         v
                 enterprise monitoring
```

## Domain contract

`control_plane/sql/070_enterprise_health_export.sql` establishes two views:

- `CONTROL.ENTERPRISE_HEALTH_EXPORT_V`: one row per logical dataset using the domain's already-evaluated health state.
- `CONTROL.DOMAIN_HEALTH_SUMMARY_V`: one row for the domain with lifecycle/status counts, open incidents and the latest evaluation timestamp.

`control_plane/sql/080_data_quality_reconciliation.sql` extends the same stable view names after DQ/reconciliation evidence is available. The dataset export then also carries:

```text
DQ_STATUS
RECONCILIATION_STATUS
LAST_DQ_AT
LAST_RECONCILIATION_AT
```

The domain summary additionally exposes failed-DQ and failed-reconciliation dataset counts plus the latest quality evidence timestamps.

The export includes a literal `DOMAIN_CODE` generated from `config/project.yml` plus `DOMAIN_DATABASE = CURRENT_DATABASE()`. This lets a central dashboard preserve domain identity without parsing database names.

The Framework deliberately does not recalculate SLA, rerun DQ rules, rerun reconciliation, or reinterpret health in the enterprise layer. `GREEN`, `YELLOW`, `RED`, `DEVELOPMENT`, `PAUSED` and `DECOMMISSIONED` continue to mean what the domain control-plane contract says they mean.

Candidate-version DQ/reconciliation evidence stays inside the domain evidence tables and release workflow. The enterprise dataset-health export reflects active-production health, not a candidate that has not been activated.

## Enterprise aggregation

A separate monitoring repository/database can explicitly choose which domains participate:

```sql
CREATE OR REPLACE VIEW ENTERPRISE_MONITORING.DATASET_HEALTH_V AS
SELECT * FROM PROD_TRANSPORT.CONTROL.ENTERPRISE_HEALTH_EXPORT_V
UNION ALL
SELECT * FROM PROD_HEALTH.CONTROL.ENTERPRISE_HEALTH_EXPORT_V
UNION ALL
SELECT * FROM PROD_FINANCE.CONTROL.ENTERPRISE_HEALTH_EXPORT_V;
```

Likewise for domain summaries:

```sql
CREATE OR REPLACE VIEW ENTERPRISE_MONITORING.DOMAIN_HEALTH_V AS
SELECT * FROM PROD_TRANSPORT.CONTROL.DOMAIN_HEALTH_SUMMARY_V
UNION ALL
SELECT * FROM PROD_HEALTH.CONTROL.DOMAIN_HEALTH_SUMMARY_V
UNION ALL
SELECT * FROM PROD_FINANCE.CONTROL.DOMAIN_HEALTH_SUMMARY_V;
```

Keep this central object read-only. Cross-domain roles/grants belong in platform infrastructure, not in the domain Framework.

Because the export is a cross-domain contract, upgrade participating domains coherently before changing a central `SELECT * UNION ALL` consumer. A safer enterprise view can also select the explicit shared column set while domains are being upgraded.

## Domain lifecycle

When a domain is paused, its export continues to expose `PAUSED` datasets. When it is soft-decommissioned, the export can remain available for the retention/audit window and expose `DECOMMISSIONED` state.

When the domain is finally removed, remove only that domain's `UNION ALL` branch and its platform read grant. No other domain control plane needs modification.

## Upgrade behavior

Fresh projects include migrations 070 and 080 in the control deploy manifest. Existing projects remain append-only: rerunning `esf init-project` creates missing SQL/docs but never rewrites an existing `control_plane/deploy_manifest.txt`.

Run `esf control-plan --project-root .`, review the reported migration gaps, and explicitly append the missing committed migrations in order. Migration 080 does not replace the existing domain-health task; its separate quality-incident task is created suspended and requires an explicit resume after review.
