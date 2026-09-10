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

`control_plane/sql/070_enterprise_health_export.sql` creates two views:

- `CONTROL.ENTERPRISE_HEALTH_EXPORT_V`: one row per logical dataset using the domain's already-evaluated health state.
- `CONTROL.DOMAIN_HEALTH_SUMMARY_V`: one row for the domain with lifecycle/status counts, open incidents and the latest evaluation timestamp.

The export includes a literal `DOMAIN_CODE` generated from `config/project.yml` plus `DOMAIN_DATABASE = CURRENT_DATABASE()`. This lets a central dashboard preserve domain identity without parsing database names.

The Framework deliberately does not recalculate SLA or reinterpret health in the enterprise layer. `GREEN`, `YELLOW`, `RED`, `DEVELOPMENT`, `PAUSED` and `DECOMMISSIONED` continue to mean whatever the domain control-plane contract says they mean.

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

## Domain lifecycle

When a domain is paused, its export continues to expose `PAUSED` datasets. When it is soft-decommissioned, the export can remain available for the retention/audit window and expose `DECOMMISSIONED` state.

When the domain is finally removed, remove only that domain's `UNION ALL` branch and its platform read grant. No other domain control plane needs modification.

## Upgrade behavior

Fresh projects include migration 070 in the control deploy manifest. Existing projects remain append-only: rerunning `esf init-project` creates the missing 070 SQL and this document but never rewrites an existing `control_plane/deploy_manifest.txt`.

Run `esf control-plan --project-root .` and explicitly add migration 070 to an existing domain manifest after review.
