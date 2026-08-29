# Workspace and Query-Tag Patterns

## Purpose

Provide reusable technical conventions for developer namespaces, ephemeral PR CI schemas, and Snowflake cost/operational attribution without putting domain business logic into the framework.

## Personal DEV workspaces

Personal development schemas live only inside `DEV_<DOMAIN>` databases and follow:

```text
<DEVELOPER>_<LAYER>
```

Examples:

```text
DEV_HEALTH.ALICE_SMITH_STAGING
DEV_HEALTH.ALICE_SMITH_MARTS
```

The framework normalises the external developer token to uppercase unquoted-Snowflake-safe characters. Stable layers are initially:

```text
STAGING
INTERMEDIATE
CANONICAL
MARTS
SEMANTIC
```

Personal schema naming is a workspace convention, **not** a security isolation boundary between developers. Platform Infra grants the shared domain `WRITE` database role `CREATE SCHEMA` only on `DEV_<DOMAIN>` databases. If stronger per-person isolation is required by a real enterprise, introduce an identity-governed personal-role pattern rather than pretending the schema prefix alone is an access-control boundary.

## PR CI workspaces

PR schemas live only inside `CI_<DOMAIN>` databases:

```text
PR_<NUMBER>_<LAYER>
```

Examples:

```text
CI_HEALTH.PR_123_STAGING
CI_HEALTH.PR_123_MARTS
```

PR workspaces are created as transient schemas with zero-day Time Travel because CI data is expected to be reproducible. They are explicitly dropped when the PR lifecycle ends.

Platform Infra owns the stable machine capability:

```text
AR_<DOMAIN>_CI
  -> DR_<DOMAIN>_CI_WORKSPACE in CI_<DOMAIN>
  -> CREATE SCHEMA on CI_<DOMAIN>
  -> USAGE on WH_<DOMAIN>_CI
```

Human GUEST/READER/DEVELOPER/ADMIN roles are not attached to `CI_<DOMAIN>` databases.

A later project CI workload identity will receive `AR_<DOMAIN>_CI`; the framework does not create Snowflake users.

## SQL renderer

Render a PR workspace:

```bash
PYTHONPATH=src python scripts/render_workspace_sql.py \
  --kind pr \
  --action create \
  --database CI_HEALTH \
  --pr-number 123 \
  --layers staging intermediate marts
```

Render cleanup:

```bash
PYTHONPATH=src python scripts/render_workspace_sql.py \
  --kind pr \
  --action drop \
  --database CI_HEALTH \
  --pr-number 123 \
  --layers staging intermediate marts
```

The renderer accepts only validated unquoted identifiers and refuses cleanup outside the expected workspace prefix. It renders SQL; execution/authentication remains the responsibility of the calling workflow.

## Query-tag contract

All framework-driven Snowflake work should eventually set a compact JSON `QUERY_TAG` using a stable vocabulary.

Required keys:

```text
project
environment
workload
```

Optional keys:

```text
source
pipeline
dataset
run_id
git_sha
pr_number
operation
```

Example:

```json
{"dataset":"patient","environment":"ci","git_sha":"abc123","pr_number":123,"project":"health","run_id":"9911","workload":"pr_ci"}
```

Do not put employee names/emails, patient/customer identifiers, secrets, sensitive values, free-form SQL, or regulated data into query tags. Query tags are operational metadata.

Render a tag:

```bash
PYTHONPATH=src python scripts/render_query_tag.py \
  --project health \
  --environment ci \
  --workload pr_ci \
  --dataset patient \
  --pr-number 123 \
  --run-id 9911 \
  --git-sha abc123
```

The builder fails before exceeding Snowflake's 2000-character `QUERY_TAG` limit rather than depending on downstream truncation.

## Attribution model

Query tags complement, rather than replace, warehouse boundaries:

```text
warehouse              -> domain/workload compute boundary
QUERY_TAG               -> project/source/pipeline/dataset/run detail
warehouse metering      -> total warehouse compute, including idle
query attribution       -> query-attributed compute, excluding idle
storage metrics         -> database/schema/table storage detail
service usage histories -> Snowpipe/Streaming/serverless costs later
```

Never treat query-attributed compute alone as the exact warehouse bill because warehouse idle time is separate.
