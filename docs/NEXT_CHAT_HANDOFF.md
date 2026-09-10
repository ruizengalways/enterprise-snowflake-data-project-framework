# Next chat handoff

Use this file first when continuing the Framework in a new conversation, then read `docs/CURRENT_CONTEXT.md`.

## Repository and stable baseline

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
main       = e578a1cde76a6dee2b5dfd41f07aa390d9b65c71
version    = 0.18.0
```

PR #25 (`feat: add trusted real-Snowflake certification suite`) is merged.

Verification for the merge SHA:

```text
Silver-first Toolkit CI #245 = SUCCESS
Snowflake Framework Certification run #1 = SKIPPED
```

The certification run was created by the successful `main` workflow-run event and its credentialed `certify` job was skipped. This is the intended safe behavior while live certification is not enabled/configured.

Do **not** call `e578a1c...` Snowflake-certified yet. The certification layer is implemented, but no real Snowflake run has produced a `CERTIFIED` artifact for this SHA.

## Stable architecture

The Framework is a developer toolkit/bootstrapper, not a production metadata interpreter.

Stable decisions:

- one business domain = one independent domain repository;
- normally one Snowflake domain database per environment/account;
- one domain may contain many sources;
- source boundaries remain visible in repo paths and Snowflake object names;
- RAW contracts are reviewed engineering declarations, not discovery output;
- standard Silver patterns are `append`, `scd1`, `scd2`, `full_refresh`, plus domain-authored `custom`;
- generated SQL becomes ordinary domain-owned source code;
- no central SCD engine, runtime metadata routing, universal ingestion runtime or deployment-time scaffolding;
- every domain owns its writable `CONTROL` schema;
- enterprise health is read-only aggregation of domain health exports;
- DQ rules remain dataset-local SQL and CONTROL stores normalized evidence;
- repair/release/lifecycle/SLA operations generate reviewable SQL and never auto-execute production changes;
- candidate versions own independent physical objects/streams/tasks/procedures and do not publish until explicit release;
- CONTROL and SILVER deployment is checksum-locked apply-once;
- applied migration path/checksum/manifest position are immutable;
- failed/started migrations block until explicit remediation;
- existing populated domains require explicit migration baseline adoption;
- new persistent version-owned objects are create-only/fail-closed;
- stable published views are replaced only during explicit release/rollback with `COPY GRANTS`;
- release starts candidate processing before publication where applicable and suspends old processing last;
- dbt remains desired-state and runs on each normal deployment.

## Trusted real-Snowflake certification now on main

Files:

```text
.github/workflows/snowflake-certification.yml
certification/README.md
certification/fixtures/canonical.yml
docs/architecture/SNOWFLAKE_CERTIFICATION.md
scripts/run_snowflake_certification.py
src/enterprise_snowflake_framework/certification_project.py
src/enterprise_snowflake_framework/certification_snowflake.py
src/enterprise_snowflake_framework/certification_scenarios.py
tests/test_snowflake_certification_contract.py
```

Security boundary:

```text
untrusted pull request
  -> credential-free Framework CI only

trusted main push CI success
  -> optional post-main certification when explicitly enabled
  -> GitHub Environment: snowflake-certification
  -> GitHub OIDC / Snowflake WIF
  -> dedicated CI_FRAMEWORK_CERT database only
```

The certification runner hard-requires:

```text
SNOWFLAKE_USER      = SU_GITHUB_FRAMEWORK_CERT
SNOWFLAKE_ROLE      = AR_FRAMEWORK_CERT
SNOWFLAKE_WAREHOUSE = WH_FRAMEWORK_CERT_TRANSFORM
SNOWFLAKE_DATABASE  = CI_FRAMEWORK_CERT
```

Grant-preservation certification also requires the pre-provisioned probe role:

```text
AR_FRAMEWORK_CERT_READER
```

The runner resets only transient schemas inside `CI_FRAMEWORK_CERT`:

```text
CONTROL
BRONZE
SILVER
```

The workflow is globally serialized and cleanup is guarded by the same fixed certification boundary.

## Certification matrix

Canonical fixtures cover:

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
- older events must not regress current state when ordering evidence exists

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
- post-v2-stream catch-up event consumed independently by v1 and v2
- DQ validation
- version comparison evidence
- explicit cutover
- rollback
- published-view SELECT grant preservation using AR_FRAMEWORK_CERT_READER

MIGRATIONS
- first apply
- identical repeat = zero apply
- checksum drift = block
- intentional failed migration = FAILED evidence
- failed migration retry = block

DYNAMIC TABLE
- NOT_APPLICABLE until a real Dynamic Table execution model exists
```

Expected results are asserted independently from the SQL renderer.

## SCD1 correctness change introduced with 0.18.0

Certification design exposed a real correctness risk in SCD1: a late-arriving older event could overwrite a newer current row.

Generated SCD1 apply SQL now uses the declared ordering tuple to require an incoming event to be strictly newer than the stored row before matched update/delete is allowed. Equal ordering is duplicate/no-op; older ordering is ignored for current-state mutation.

Do not weaken the certification fixture if Snowflake exposes another edge case. Treat the failing fixture as product evidence and fix the generator through a normal PR.

## Required Snowflake/GitHub setup before first live certification

Provision outside Framework runtime code:

```text
GitHub Environment: snowflake-certification
GitHub environment vars:
  SNOWFLAKE_ACCOUNT
  SNOWFLAKE_OIDC_AUDIENCE

Snowflake:
  CI_FRAMEWORK_CERT
  AR_FRAMEWORK_CERT
  AR_FRAMEWORK_CERT_READER
  SU_GITHUB_FRAMEWORK_CERT
  WH_FRAMEWORK_CERT_TRANSFORM
```

Recommended WIF subject:

```text
repo:ruizengalways/enterprise-snowflake-data-project-framework:environment:snowflake-certification
```

Use an account-scoped OIDC audience.

Effective certification role requirements include create/drop-schema rights inside the dedicated certification database, warehouse USAGE, global `EXECUTE TASK`, global `EXECUTE MANAGED TASK`, and authority to grant/revoke SELECT on the certification published view to the reader probe role.

For the first live run, use manual dispatch from `main`. After that run is proven and environment protection is in place, set:

```text
ESF_SNOWFLAKE_CERTIFICATION_ENABLED=true
```

so successful main push CI automatically starts certification.

## Status wording

Until a real workflow artifact says `status = CERTIFIED` for the exact SHA, use this wording:

> The Framework has a trusted Snowflake certification layer implemented, but this SHA has not yet been certified in a real Snowflake account.

Successful artifacts are:

```text
snowflake-certification.json
snowflake-certification.md
```

They record the exact Framework Git SHA and Snowflake version.

## What to do next

In the next conversation:

1. read this file and `docs/CURRENT_CONTEXT.md`;
2. re-check current `main`, open PRs and CI before modifying anything;
3. do not rebuild the certification layer—it is already merged in 0.18.0;
4. if certification infrastructure is still absent, provision the dedicated Snowflake/GitHub boundary described above;
5. manually run `Snowflake Framework Certification` from `main` for the exact current trusted SHA;
6. inspect the first real failure as product evidence and fix the Framework rather than weakening expected fixtures;
7. only after a real successful run describe that exact SHA as Snowflake-certified;
8. after certification is stable, the next major framework feature candidate is release-readiness gating or a separately justified Dynamic Table execution model—not additional generic runtime abstraction.
