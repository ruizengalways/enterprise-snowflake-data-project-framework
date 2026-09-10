# DDL safety and release cutover

## Purpose

Apply-once migration history prevents an already-applied SQL file from being replayed, but the SQL inside a new migration still needs safe object semantics. This document defines the default DDL contract for generated Snowflake objects and explicit dataset releases.

The framework does not hide DDL behind a runtime metadata engine. Generated SQL remains committed, readable and domain-owned.

## Persistent object rule

A newly scaffolded implementation version owns unique physical names. Persistent version-owned objects therefore use create-only DDL:

```text
TABLE       -> CREATE TABLE
STREAM      -> CREATE STREAM
VIEW        -> CREATE VIEW
PROCEDURE   -> CREATE PROCEDURE
TASK        -> CREATE TASK
```

The generated migration deliberately does not use `IF NOT EXISTS` or `OR REPLACE` for those names. If an object unexpectedly exists before its apply-once migration runs, deployment fails so the ownership conflict can be investigated.

This rule applies to V1 and candidate V2/V3 implementation objects generated after this contract was introduced. Existing domain-owned SQL is never rewritten by a framework upgrade.

## Why tasks are create-only

Snowflake creates a new task suspended. Replacing an existing task can therefore reset runtime activation state. Generated version-owned tasks use plain `CREATE TASK`; activation is a separate explicit lifecycle action using `ALTER TASK ... RESUME`.

Apply-once migration history adds a second guard: after the task migration succeeds, later deployments skip that migration rather than re-running it. Deploying an unrelated dataset therefore does not recreate or suspend an already-active task.

If a task definition needs to change after deployment, append a reviewed migration or create a new implementation version. Do not edit an already-applied migration in place.

## Published consumer views

Stable Silver published names are the intentional routing boundary between consumers and implementation versions.

Initial V1 publication is create-only:

```sql
CREATE VIEW SILVER.<DATASET>_CURRENT AS ...;
```

If that stable name unexpectedly exists, initial publication fails instead of silently replacing an unknown object.

A V1 -> V2 cutover is different: changing the stable view definition is the intended operation. Release SQL therefore uses:

```sql
CREATE OR REPLACE VIEW SILVER.<DATASET>_CURRENT COPY GRANTS AS ...;
```

`COPY GRANTS` preserves explicit privileges on the prior view except OWNERSHIP. The generated rollback uses the same grant-preserving replacement pattern.

The framework never uses candidate deployment itself to replace the stable published view. Candidate `050_publish.sql` remains a no-op comment; publication only occurs in an explicitly generated release operation.

## Release ordering

Release SQL is intentionally ordered to minimize outage risk:

```text
candidate validated and caught up
    -> start candidate triggered task when applicable
    -> replace stable published view(s) with COPY GRANTS
    -> update CONTROL active-version state
    -> mark prior version retired
    -> suspend prior task last
```

The old task is not suspended as the first release side effect. If publication or a preceding step fails, the previously active implementation keeps processing.

Snowflake DDL commits independently, so release SQL is not presented as one rollback-able transaction. If a step fails after publication, inspect the actual state and use the generated rollback or an explicit corrective operation; do not blindly replay a partially completed release script.

Full-refresh versions have no readiness schedule by default. Their release script does not guess task activation; the candidate snapshot must already be rebuilt and validated before publication.

## Intentional OR REPLACE exceptions

Not every `OR REPLACE` is unsafe. The framework retains it in two explicit cases:

1. Stable published view replacement during reviewed release/rollback, always with `COPY GRANTS`.
2. `CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE` inside a stored procedure. These are invocation-scoped working tables, not persistent production objects or consumer contracts.

Released CONTROL migrations 001-080 can contain historical replacement DDL. They are immutable and protected by apply-once deployment, so this change does not rewrite them. Future CONTROL replacement migrations must be appended and should preserve grants/state where applicable.

## Procedure upgrades

Generated apply, replay and validation procedures are create-only for a new implementation version. A later code change must not modify the already-applied migration. Preferred options are:

- append a new reviewed migration using Snowflake-supported alteration/replacement semantics appropriate to the object and required grant behavior; or
- scaffold a candidate implementation version when transformation behavior changes materially.

The framework does not provide a central generic procedure updater.

## Relationship to apply-once migrations

DDL safety and migration safety are complementary:

```text
apply-once history
    answers: should this committed SQL file execute?

DDL safety
    answers: if a new file executes, what may it safely create or replace?
```

Both are required. A create-only migration can still be dangerous if replayed repeatedly, and an apply-once runner can still execute unsafe replacement DDL the first time.

## Operational invariants

The following are regression-tested framework invariants:

- adding another dataset does not re-execute an existing task migration;
- newly generated version-owned tasks are never `CREATE OR REPLACE TASK`;
- unexpected pre-existing version-owned objects fail rather than being silently replaced;
- candidate deployment does not modify stable published consumer views;
- release and rollback preserve published-view grants with `COPY GRANTS`;
- candidate task activation, when applicable, occurs before publication;
- prior active task suspension occurs after publication and CONTROL cutover work;
- procedure-scoped temporary working tables remain allowed to use `OR REPLACE`.
