# Snowflake certification operator guide

This directory contains the deterministic fixtures used by the trusted real-Snowflake certification workflow.

## Before enabling

Provision the dedicated certification boundary described in `docs/architecture/SNOWFLAKE_CERTIFICATION.md`:

```text
CI_FRAMEWORK_CERT
AR_FRAMEWORK_CERT
SU_GITHUB_FRAMEWORK_CERT
WH_FRAMEWORK_CERT_TRANSFORM
GitHub Environment: snowflake-certification
```

The GitHub Environment must define:

```text
SNOWFLAKE_ACCOUNT
SNOWFLAKE_OIDC_AUDIENCE
```

Keep `ESF_SNOWFLAKE_CERTIFICATION_ENABLED` unset/false until the Snowflake and GitHub environment controls are ready.

## First run

Use **Actions -> Snowflake Framework Certification -> Run workflow** from `main`.

A successful run produces an artifact named:

```text
snowflake-certification-<framework-sha>
```

containing `snowflake-certification.json` and `snowflake-certification.md`.

Only after the exact SHA reports `CERTIFIED` should release notes call that Framework revision Snowflake-certified.

## Automatic post-main certification

After the manual run is proven and environment protection is in place, set:

```text
ESF_SNOWFLAKE_CERTIFICATION_ENABLED=true
```

A successful `Silver-first Toolkit CI` **push run on main** will then trigger certification. Pull-request workflow runs are explicitly rejected by the certification job condition and never receive the certification Snowflake identity.

## Fixture ownership

`fixtures/canonical.yml` is machine-owned test evidence, not a domain RAW contract example. Change it only when intentionally changing the certification matrix and review expected semantic outcomes at the same time.

Current matrix:

```text
append          real Snowflake
scd1            real Snowflake
scd2            real Snowflake
full_refresh    real Snowflake
dynamic_table   NOT_APPLICABLE until implemented
```

The certification runner creates a temporary domain repository with the same public scaffold/version APIs that a domain engineer uses, then deploys it through the real apply-once migration CLI.

## Failure handling

A certification failure is evidence, not something to auto-remediate. Inspect the failing pattern or Snowflake behavior, fix the Framework on a normal branch/PR, and rerun certification after the fix reaches trusted `main`.

The workflow always attempts to drop only `CI_FRAMEWORK_CERT.{CONTROL,BRONZE,SILVER}` after authentication succeeds. Do not point the runner at another database; it contains hard guards against that.
