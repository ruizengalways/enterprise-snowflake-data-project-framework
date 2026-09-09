# Workspace and query-tag patterns

## Workspace surface

Ephemeral personal/PR workspaces mirror the active architecture schemas:

```text
BRONZE
SILVER_CANONICAL
GOLD_MARTS
GOLD_SEMANTIC
DQ
```

`SILVER_STAGING` and `SILVER_INTERMEDIATE` are no longer part of the canonical project runtime. Bronze is ingestion evidence, Silver Canonical is explicit domain-owned processing, and dbt starts from trusted Silver to build Gold/Semantic.

PR schemas use `PR_<NUMBER>_<LAYER>` inside `CI_<DOMAIN>`. Personal DEV schemas use `<DEVELOPER>_<LAYER>` inside `DEV_<DOMAIN>`. Workspace prefixes are naming conventions, not substitutes for identity/RBAC isolation.

The reusable PR workflow creates/drops only validated workspace schema names. It does not execute untrusted pull-request transformation code while holding Snowflake credentials.

## Query tags

Query tags remain compact operational metadata. Required keys are project/environment/workload; optional keys include source, pipeline, dataset, run_id, git_sha, pr_number and operation.

Do not put employee identifiers, customer/patient identifiers, secrets, SQL or regulated values into query tags.

Warehouse boundaries provide coarse domain/workload cost attribution; query tags add project/pipeline/run detail. Query-attributed compute does not equal the complete warehouse bill because idle warehouse time is separate.
