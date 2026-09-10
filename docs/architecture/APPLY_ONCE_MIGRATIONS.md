# Apply-once migration deployment

## Purpose

CONTROL and SILVER deployment SQL is committed source code, but committed source is not the same thing as "execute every historical file on every deployment".

The deployment contract is therefore apply-once and checksum-locked per Snowflake environment.

This keeps the existing ownership rule:

```text
generated once
-> reviewed
-> committed
-> domain-owned forever
```

while adding a second production rule:

```text
once a migration has been applied or baselined in an environment
-> its path, manifest position and file bytes are immutable in that environment
```

Changing production behavior requires a new migration path or a new dataset implementation version. Do not edit an already-applied migration in place.

## Scope

The apply-once runner manages only:

```text
control_plane/deploy_manifest.txt
silver_processing/deploy_manifest.txt
```

It does not manage:

- dbt models; `dbt build` remains desired-state execution on each deployment
- generated `operations/release/` SQL
- generated `operations/repair/` SQL
- generated lifecycle/SLA operation scripts
- ingestion connector runtime
- source profiling

Those are separate operational lifecycles.

## Environment-local history

Every domain environment has its own:

```text
CONTROL.DEPLOYMENT_HISTORY
```

DEV, UAT and PROD therefore have independent application state even when they deploy the same repository commit.

The bootstrap table records:

- deployment attempt ID
- migration scope: `CONTROL` or `SILVER`
- repository-relative migration path
- SHA-256 checksum of the exact checked-out file bytes
- manifest position within that scope
- immutable project Git SHA
- immutable Framework Git SHA
- status
- started/finished timestamps
- error code/details
- GitHub Actions run ID when available
- operator reason for explicit baseline/remediation events

## Bootstrap exception

`CONTROL.DEPLOYMENT_HISTORY` is required before normal migrations can be tracked. The runner therefore performs one deliberately tiny idempotent bootstrap before it reads migration history:

```sql
CREATE SCHEMA IF NOT EXISTS CONTROL;
CREATE TABLE IF NOT EXISTS CONTROL.DEPLOYMENT_HISTORY (...);
```

This bootstrap is Framework implementation infrastructure, pinned by `framework_ref`. It is not a general-purpose migration and does not execute domain transformation logic.

Everything listed in the CONTROL and SILVER manifests follows normal apply-once rules.

## State machine

For one current committed migration:

```text
no history
  -> APPLY

SUCCEEDED + same checksum + same position
  -> SKIP

BASELINED + same checksum + same position
  -> SKIP

REMEDIATED + same checksum + same position
  -> SKIP

STARTED
  -> BLOCK

FAILED
  -> BLOCK

previously recorded path removed from manifest
  -> BLOCK

previously recorded path moved to another manifest position
  -> BLOCK

previously recorded path has a different checksum
  -> BLOCK
```

The runner never silently retries a `STARTED` or `FAILED` migration.

## Why STARTED/FAILED block

Snowflake DDL is not an all-or-nothing multi-statement transaction. A DDL statement executes as its own transaction and cannot be rolled back as part of a later migration failure.

A file can therefore partially change Snowflake and then fail on a later statement.

The runner records `STARTED` before executing the file. If execution fails it records `FAILED` and stops. If the GitHub runner dies after Snowflake starts work but before the final history update, the `STARTED` row remains and the next deployment stops for investigation.

An engineer must inspect partial state, repair it explicitly if necessary, and then use the explicit remediation command. The migration file is not automatically re-executed.

## New domain first deployment

For a genuinely empty domain environment:

```text
history empty
CONTROL/SILVER managed objects absent
  -> bootstrap DEPLOYMENT_HISTORY
  -> apply CONTROL migrations once
  -> apply SILVER migrations once
  -> record each success
  -> dbt build
```

A second deployment of the exact same project Git SHA should execute zero CONTROL/SILVER migration files.

## Existing populated domain adoption

This is the most important upgrade rule.

If `CONTROL.DEPLOYMENT_HISTORY` is empty but the target database already contains CONTROL or SILVER managed objects, normal deployment blocks. It does not assume the historical manifests are safe to re-run.

Adoption is explicit:

```text
choose the exact already-deployed project Git SHA
        ↓
review CONTROL and SILVER manifests against the actual environment
        ↓
confirm existing state is represented by those exact files
        ↓
run `esf-migrate baseline ... --confirm-existing-state-reviewed`
        ↓
record every current manifest file as BASELINED
        ↓
execute zero historical migration files
```

Baseline is allowed only when managed objects already exist and deployment history is still empty.

Example:

```bash
esf-migrate baseline \
  --project-root . \
  --project-git-sha <40-char-domain-sha> \
  --framework-git-sha <40-char-framework-sha> \
  --reason "Adopt existing PROD state after manifest/object review" \
  --confirm-existing-state-reviewed
```

Do not baseline a fresh empty environment just to avoid executing its first deployment.

## Failure remediation

A `STARTED` or `FAILED` row blocks future deployment for that migration.

After investigating partial state, the engineer may:

1. manually finish/repair the intended state, or add a separate corrective migration;
2. keep the original failed migration file unchanged;
3. explicitly record the original path as remediated.

Example:

```bash
esf-migrate resolve \
  silver_processing/fleet_mssql/customer/090_fix_task.sql \
  --project-root . \
  --project-git-sha <40-char-domain-sha> \
  --framework-git-sha <40-char-framework-sha> \
  --reason "Verified task state and applied corrective migration 100" \
  --confirm-partial-state-reviewed
```

`resolve` does not execute the failed file. It only writes a new `REMEDIATED` audit event after verifying the path, checksum and manifest position still match the failed/started attempt.

## Append-only manifests

The migration history protects both file content and sequence.

If an environment has already recorded:

```text
A
B
C
```

future manifests may become:

```text
A
B
C
D
E
```

but not:

```text
A
C
B
D
```

or:

```text
A
C
D
```

or:

```text
X
A
B
C
```

Domain-owned extra migrations are allowed, but once applied they are also locked to their recorded position and checksum.

## Framework control migration immutability

Framework-released control migration templates are immutable once published.

For example, if `080_data_quality_reconciliation.sql` needs a correction after release, Framework development must add a later migration such as `090_...sql`; it must not change the released 080 template in place.

Framework CI blocks modifications/deletions/renames of already-existing numbered control migration templates. Adding a new numbered migration is allowed.

This prevents different domains from receiving different bytes under the same migration path.

## Deployment concurrency

The reusable deployment workflow uses a GitHub Actions concurrency group keyed by:

```text
project_code + environment
```

with `cancel-in-progress: false`.

This prevents two normal authorized deployments for the same domain/environment from independently deciding that the same new migration has not yet run.

The supported production path is the reusable deployment workflow. Out-of-band manual deployment bypasses that concurrency protection and must be operationally controlled.

## Deterministic deployment order

Normal deployment order is:

```text
validate immutable project/framework SHAs
        ↓
project contract validation
        ↓
control baseline preflight
        ↓
manifest path/file safety validation
        ↓
Snowflake OIDC authentication
        ↓
bootstrap CONTROL.DEPLOYMENT_HISTORY
        ↓
apply/skip CONTROL migrations in committed manifest order
        ↓
apply/skip SILVER migrations in committed manifest order
        ↓
dbt debug
        ↓
dbt build
```

No scaffold command runs during deployment.

## Developer lifecycle after apply-once adoption

Before a migration has reached an environment, engineers may edit it normally through PR review.

After it has reached an environment, do not change that path's bytes. Add a new migration instead.

Examples:

```text
active V1 implementation bug
  -> prefer V2 candidate + replay + validation + release

small operational object patch that intentionally stays on V1
  -> add a new explicit SQL migration path to silver_processing/deploy_manifest.txt

control-plane change
  -> add a later numbered control migration; do not rewrite an older released migration
```

Release/repair/lifecycle scripts remain explicit engineer-run operations and are not automatically appended to normal deployment manifests.

## Non-goals

The migration runner is not:

- a runtime metadata engine
- a dynamic SQL generator
- a generic SCD procedure
- a schema discovery tool
- an autonomous production repair engine
- a replacement for dbt

It only controls whether committed SQL files are allowed to execute in a particular environment.
