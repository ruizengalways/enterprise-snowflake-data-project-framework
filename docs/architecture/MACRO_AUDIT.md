# Macro audit: clean hybrid v2

The v2 cleanup applies this policy:

| Previous area | Decision | v2 home / reason |
| --- | --- | --- |
| `capture/*` | DELETE / REHOME | Naming implied source ingestion ownership. Landed-data lifecycle helpers move under processing/checkpoint/runtime control. |
| `loading/strategies.sql` | DELETE | Standard dbt config or one bounded dataset-config helper; no strategy SQL generator. |
| `operations/domain_control.sql` | KEEP AS MACRO | Domain-scoped guarded control-plane procedure/view calls are reusable technical behavior. |
| `operations/reset.sql` | KEEP AS MACRO | Bounded lifecycle mechanics; explicit domain reset plans remain domain-owned. |
| `operations/runtime.sql` | KEEP AS MACRO | Run/checkpoint registration is control-plane mechanics. |
| `quality/*` | KEEP AS MACRO | Bounded reusable DQ helpers only. |
| SCD2 SQL generator | MOVE TO MATERIALIZATION / NATIVE SQL | SCD2 correctness is a justified stateful materialization; domain select SQL stays readable. |
| Dynamic Table DDL helpers | MOVE TO NATIVE/DBT MATERIALIZATION | Dynamic Table is a materialization/runtime capability, not a load strategy. |
| business transformations | MOVE TO DOMAIN SQL | Framework never describes joins, aggregates or business expressions. |

No compatibility aliases are retained for v1 names.
