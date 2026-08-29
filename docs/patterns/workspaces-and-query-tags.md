# Workspace and Query-Tag Patterns

## Purpose

Provide reusable technical conventions for developer namespaces, ephemeral PR CI schemas, project delivery and Snowflake cost/operational attribution without putting domain business logic into the framework.

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

The framework normalizes the external developer token to uppercase unquoted-Snowflake-safe characters. Stable layers are initially:

```text
STAGING
INTERMEDIATE
CANONICAL
MARTS
SEMANTIC
```

Personal schema naming is a workspace convention, **not** a security isolation boundary between developers. Platform Infra grants the shared domain WRITE database role `CREATE SCHEMA` only on `DEV_<DOMAIN>` databases. If stronger per-person isolation is required, introduce an identity-governed personal-role pattern rather than treating the schema prefix as access control.

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

PR workspaces are transient schemas with zero-day Time Travel because CI data is expected to be reproducible. They are explicitly dropped when the PR lifecycle ends.

Platform Infra owns the stable machine capability:

```text
SU_GITHUB_<DOMAIN>_CI
  -> AR_<DOMAIN>_CI
      -> CI_<DOMAIN>.DR_<DOMAIN>_CI_WORKSPACE
      -> CREATE SCHEMA on CI_<DOMAIN>
      -> USAGE on WH_<DOMAIN>_CI
      -> EXECUTE TASK
```

Human GUEST/READER/DEVELOPER/ADMIN roles are not attached to `CI_<DOMAIN>` databases. The project-CI service identity is created by the platform `project-identity/dev` lifecycle; the framework never creates Snowflake users/roles.

The reusable PR workflow executes only framework-generated workspace lifecycle SQL while authenticated. It does not execute untrusted PR business code under Snowflake credentials.

## Workspace SQL renderer

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

## Stable deployment identity

Stable DEV/UAT/PROD dbt delivery uses a different machine identity:

```text
SU_GITHUB_<DOMAIN>_DEPLOY
  -> AR_<DOMAIN>_DEPLOY
  -> WH_<DOMAIN>_TRANSFORM
  -> stable <ENV>_<DOMAIN> schemas
```

Do not reuse PR-CI identities for stable deployment. Project deployment workflows promote a reviewed full Git SHA and do not use environment branches.

## Query-tag contract

Framework-driven Snowflake work uses compact JSON `QUERY_TAG` metadata with a stable vocabulary.

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

Do not put employee names/emails, patient/customer identifiers, secrets, sensitive values, free-form SQL or regulated data into query tags. Query tags are operational metadata.

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
