# Trusted Snowflake certification

## Purpose

Framework unit tests prove Python, scaffolding and repository contracts. They do not prove that generated SQL behaves correctly inside a real Snowflake account.

The certification layer is a separate trusted acceptance gate. A Framework revision is **not** described as Snowflake-certified until this workflow has completed successfully for that exact immutable Git SHA.

```text
credential-free PR CI
  -> merge to trusted main
  -> normal main CI succeeds
  -> trusted Snowflake certification
  -> real generated CONTROL/SILVER SQL
  -> deterministic assertions
  -> cleanup
  -> certification artifact
```

## Security boundary

`.github/workflows/snowflake-certification.yml` deliberately has no `pull_request` trigger.

Automatic certification only follows a successful `push` run of `Silver-first Toolkit CI` on `main`, only when repository/environment variable `ESF_SNOWFLAKE_CERTIFICATION_ENABLED` is set to `true`. Manual dispatch is accepted only from `main`.

The credentialed job targets the GitHub Environment:

```text
snowflake-certification
```

The job resolves one immutable trusted Framework SHA, checks out that SHA explicitly and verifies the checkout before obtaining Snowflake credentials. Untrusted PR head code is never the source of SQL executed by this workflow.

The GitHub Environment should require review/branch protection appropriate for the repository. Snowflake WIF should bind the service user to the environment subject:

```text
repo:ruizengalways/enterprise-snowflake-data-project-framework:environment:snowflake-certification
```

Use an account-scoped OIDC audience rather than the shared `snowflakecomputing.com` default.

## Snowflake isolation model

The first implementation intentionally does **not** grant the certification role account-level `CREATE DATABASE`.

Platform infrastructure creates one dedicated database:

```text
CI_FRAMEWORK_CERT
```

Every certification run deletes and recreates only these schemas:

```text
CI_FRAMEWORK_CERT.CONTROL
CI_FRAMEWORK_CERT.BRONZE
CI_FRAMEWORK_CERT.SILVER
```

They are recreated as transient schemas. The workflow is globally serialized with `cancel-in-progress: false`, so two certification runs cannot share these fixed schema names concurrently.

The runner refuses to operate unless the connection environment exactly names:

```text
user:      SU_GITHUB_FRAMEWORK_CERT
role:      AR_FRAMEWORK_CERT
warehouse: WH_FRAMEWORK_CERT_TRANSFORM
database:  CI_FRAMEWORK_CERT
```

This fixed-name guard is intentional. Do not reuse the certification runner against a domain DEV/UAT/PROD database.

## Required platform setup

An administrator should provision the dedicated objects outside this repository's runtime code. The exact grant hierarchy is an infrastructure concern, but the effective certification role needs:

- ownership of, or sufficient create/drop-schema privileges within, `CI_FRAMEWORK_CERT`;
- USAGE on `WH_FRAMEWORK_CERT_TRANSFORM`;
- global `EXECUTE TASK` for user-managed dataset tasks;
- global `EXECUTE MANAGED TASK` because current CONTROL migrations create serverless health tasks;
- normal privileges inherited from ownership of the transient certification schemas to create tables, streams, views, procedures and tasks there.

The service user uses Snowflake Workload Identity Federation with GitHub OIDC. A representative shape is:

```sql
CREATE USER SU_GITHUB_FRAMEWORK_CERT
  TYPE = SERVICE
  WORKLOAD_IDENTITY = (
    TYPE = OIDC
    ISSUER = 'https://token.actions.githubusercontent.com'
    SUBJECT = 'repo:ruizengalways/enterprise-snowflake-data-project-framework:environment:snowflake-certification'
    OIDC_AUDIENCE_LIST = ('<account-scoped-audience>')
  );
```

Grant `AR_FRAMEWORK_CERT` to that service user and configure the GitHub Environment variables:

```text
SNOWFLAKE_ACCOUNT
SNOWFLAKE_OIDC_AUDIENCE
```

The repository-level opt-in for automatic post-main certification is:

```text
ESF_SNOWFLAKE_CERTIFICATION_ENABLED=true
```

Keep it disabled until the Snowflake user/role/database/warehouse and GitHub Environment protection are ready. Manual workflow dispatch is useful for the first acceptance run.

## What is executed

The workflow builds a temporary canonical domain repository with the public Framework APIs. It does not use hand-written substitute Silver SQL.

The fixture project contains four standard patterns:

```text
append
scd1
scd2
full_refresh
```

The runner then:

1. creates deterministic Bronze tables and fixture rows;
2. deploys generated CONTROL and Silver migrations through the real `esf-migrate` CLI;
3. redeploys the same project SHA and asserts zero migrations re-execute;
4. calls generated apply/validate/replay procedures;
5. executes one suspended task manually with `EXECUTE TASK`;
6. resumes a generated triggered task, inserts Bronze evidence and confirms `TASK_HISTORY.SCHEDULED_FROM = 'TRIGGER'`;
7. scaffolds and deploys SCD2 candidate `v2` as a later migration append;
8. bootstraps/replays v2 and runs candidate validation/comparison;
9. performs explicit cutover and rollback using generated release SQL;
10. verifies the published-view SELECT grant survives both replacements;
11. intentionally changes one already-applied migration byte and requires checksum blocking;
12. appends an intentionally failing migration, requires `FAILED` deployment history, and requires the next deployment to block instead of retrying;
13. writes machine-readable and human-readable certification artifacts.

## Canonical semantic cases

`certification/fixtures/canonical.yml` is the machine-owned fixture contract. It includes:

- initial insert;
- duplicate delivery;
- update;
- tombstone/delete;
- reinsert;
- late-arriving event;
- out-of-order event;
- SCD2 full replay;
- candidate v2 bootstrap;
- release cutover and rollback.

The expected result is asserted independently by `certification_snowflake.py`; it is not derived by reusing the transformation renderer as the oracle.

Dynamic Tables are intentionally reported as `NOT_APPLICABLE` until the Framework has a real Dynamic Table execution model. Do not implement a feature merely to make the certification matrix green.

## Task assertions

The certification suite separates transformation semantics from orchestration semantics.

Most fixture steps call the generated apply procedure directly so transformation failures are deterministic and easy to diagnose. Task behavior is then certified separately:

- a suspended full-refresh task is invoked with `EXECUTE TASK` and must finish successfully;
- an append triggered task is resumed, new stream data is inserted, and Snowflake `TASK_HISTORY` must report a successful execution with `SCHEDULED_FROM = 'TRIGGER'`.

This proves both the procedure logic and the native Task/Stream integration without making every semantic assertion depend on asynchronous scheduling.

## Cleanup

The workflow has an `always()` cleanup step after OIDC succeeds. It drops only the fixed certification schemas. A later run also begins by resetting those schemas, so stale resources from an interrupted runner do not get silently reused.

Cleanup failure must remain visible as a failed workflow. It is not converted into a warning.

## Certification artifact

Each run uploads:

```text
snowflake-certification.json
snowflake-certification.md
```

The JSON records the Framework SHA/version, Snowflake version, certification database, overall status and individual checks. Only `status = CERTIFIED` for the exact Framework SHA supports the statement:

> This Framework revision is certified against real Snowflake behavior.

A normal green PR/main CI without this artifact means the revision passed static/repository tests, not that it has completed real Snowflake certification.
