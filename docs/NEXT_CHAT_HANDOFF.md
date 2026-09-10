# Next chat handoff

Use this file as the first context document when continuing the Framework in a new conversation.

## Repository

```text
ruizengalways/enterprise-snowflake-data-project-framework
```

Base before this change:

```text
main = b55b03fba02720d641098a91fe384357da672adb
version = 0.17.0
```

Current feature branch while this work is under review:

```text
feature/snowflake-certification-suite
planned version = 0.18.0
```

Do not assume this branch is merged until PR/CI/main-push status is checked.

## Stable architecture already on main

The Framework is a developer toolkit/bootstrapper, not a production metadata interpreter.

Stable decisions:

- one business domain = one independent domain repository;
- normally one Snowflake domain database per environment/account;
- a domain may contain many source systems;
- source boundaries remain visible in repo paths and Snowflake object names;
- RAW contracts are reviewed engineering declarations, not source-discovery output;
- standard Silver patterns are `append`, `scd1`, `scd2`, `full_refresh`, plus domain-authored `custom`;
- generated SQL becomes ordinary domain-owned source code;
- no central SCD engine, runtime metadata routing, universal ingestion runtime or deployment-time scaffolding;
- every domain owns its writable `CONTROL` schema;
- enterprise health is read-only aggregation of domain health exports;
- DQ rules remain dataset-local SQL; CONTROL stores normalized evidence only;
- repair/release/lifecycle/SLA operations generate reviewable SQL and never auto-execute production changes;
- candidate versions own independent physical objects/streams/tasks/procedures and do not publish until explicit release;
- CONTROL and SILVER deployment is checksum-locked apply-once;
- applied migration path/checksum/manifest position are immutable;
- failed/started migrations block until explicit remediation;
- existing populated domains require explicit migration baseline adoption;
- newly generated persistent version-owned objects are create-only/fail-closed;
- stable published views are replaced only during explicit release/rollback and use `COPY GRANTS`;
- release starts candidate processing before publication where applicable and retires/suspends old processing last;
- dbt remains desired-state and runs on each normal deployment.

## Trusted Snowflake certification work

The feature branch adds a real Snowflake acceptance/certification layer. It is intentionally separate from ordinary PR CI.

Files:

```text
.github/workflows/snowflake-certification.yml
certification/README.md
certification/fixtures/canonical.yml
docs/architecture/SNOWFLAKE_CERTIFICATION.md
scripts/run_snowflake_certification.py
src/enterprise_snowflake_framework/certification_project.py
src/enterprise_snowflake_framework/certification_snowflake.py
tests/test_snowflake_certification_contract.py
```

Certification security boundary:

```text
untrusted pull request
  -> credential-free Framework CI only

trusted main push CI success
  -> optional post-main certification when enabled
  -> GitHub Environment snowflake-certification
  -> GitHub OIDC / Snowflake WIF
  -> dedicated CI_FRAMEWORK_CERT database only
```

The runner hard-requires:

```text
SNOWFLAKE_USER      = SU_GITHUB_FRAMEWORK_CERT
SNOWFLAKE_ROLE      = AR_FRAMEWORK_CERT
SNOWFLAKE_WAREHOUSE = WH_FRAMEWORK_CERT_TRANSFORM
SNOWFLAKE_DATABASE  = CI_FRAMEWORK_CERT
```

It resets only transient schemas:

```text
CONTROL
BRONZE
SILVER
```

within that dedicated database. The certification workflow is globally serialized.

## Certification matrix

Canonical fixtures exercise:

```text
APPEND
- initial insert
- duplicate delivery
- native triggered Task/Stream execution

SCD1
- insert
- update
- duplicate
- late arrival
- delete/tombstone
- reinsert
- out-of-order event

SCD2
- insert
- update
- late-arriving history reconstruction
- delete/tombstone
- reinsert
- full replay

FULL_REFRESH
- initial snapshot
- manual EXECUTE TASK
- replacement snapshot

VERSION / RELEASE
- v2 scaffold as later committed migrations
- v2 bootstrap/replay
- DQ validation
- version comparison evidence
- explicit cutover
- rollback
- published-view SELECT grant preservation

MIGRATIONS
- first apply
- identical repeat = zero apply
- checksum drift = block
- intentional failed migration = FAILED evidence
- failed migration retry = block

DYNAMIC TABLE
- NOT_APPLICABLE until a real Dynamic Table execution model exists
```

The expected semantic result is asserted independently from the SQL renderer.

## Required Snowflake/GitHub setup before first live run

Create/provision outside runtime Framework code:

```text
GitHub Environment: snowflake-certification
GitHub environment vars:
  SNOWFLAKE_ACCOUNT
  SNOWFLAKE_OIDC_AUDIENCE

Snowflake:
  CI_FRAMEWORK_CERT
  AR_FRAMEWORK_CERT
  SU_GITHUB_FRAMEWORK_CERT
  WH_FRAMEWORK_CERT_TRANSFORM
```

WIF subject should be:

```text
repo:ruizengalways/enterprise-snowflake-data-project-framework:environment:snowflake-certification
```

Use an account-scoped OIDC audience.

The effective certification role needs create/drop-schema rights inside the dedicated certification database, warehouse USAGE, global `EXECUTE TASK`, and global `EXECUTE MANAGED TASK`.

After the first manual certification is proven, set:

```text
ESF_SNOWFLAKE_CERTIFICATION_ENABLED=true
```

so successful main push CI can automatically trigger certification.

## Important status distinction

Until a real certification workflow run finishes with artifact status `CERTIFIED`, say:

> The Framework has a trusted Snowflake certification layer implemented, but this SHA has not yet been certified in a real Snowflake account.

Do not say a revision is Snowflake-certified merely because ordinary CI is green.

Successful certification artifacts are:

```text
snowflake-certification.json
snowflake-certification.md
```

and record the exact Framework Git SHA plus Snowflake version.

## What to do next

When opening the next conversation:

1. read this file and `docs/CURRENT_CONTEXT.md`;
2. check current `main`, open PRs and CI status before modifying anything;
3. if the certification PR is not merged, finish its ordinary credential-free CI first;
4. if merged but Snowflake/GitHub certification infrastructure is not configured, provision it outside the Framework runtime and run the workflow manually from `main`;
5. inspect the first real certification failure as product evidence—do not weaken expected semantics to make it green;
6. only after a real successful run describe that exact SHA as Snowflake-certified.

Potential first live issue to pay particular attention to: SCD1 late/out-of-order handling. The certification fixture deliberately asserts that an older source event arriving later must not regress the current row. If real certification exposes a bug, fix the generator through a new Framework PR and rerun certification rather than changing the fixture expectation.
