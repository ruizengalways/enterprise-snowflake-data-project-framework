# Deployment control-plane preflight

## Problem

A domain repository can intentionally lag a Framework control-plane upgrade because `esf init-project` never rewrites the domain-owned `control_plane/deploy_manifest.txt`.

That append-only rule is correct for ownership, but deployment must not silently ignore the gap. A newer Silver scaffold can depend on a newer control-plane contract. For example, current dataset validation writes `CONTROL.DQ_RESULT`, which is introduced by migration 080.

The unsafe sequence is:

```text
upgrade Framework package
  -> init-project creates missing migration file
  -> domain forgets to append migration to deploy manifest
  -> deploy continues
  -> Silver code reaches a runtime dependency that was never deployed
```

## Rule

Interactive upgrade planning and deployment enforcement are separate concerns:

```text
esf control-plan
  -> read-only human report
  -> never modifies the manifest

esf-control-preflight
  -> read-only repository CI gate
  -> non-zero exit when the current Framework control baseline is not deployable

esf-migrate deploy
  -> environment-aware apply-once runner after authentication
  -> uses CONTROL.DEPLOYMENT_HISTORY to APPLY / SKIP / BLOCK exact files
```

The reusable project deployment workflow runs `esf-control-preflight --project-root project` before requesting a Snowflake OIDC token.

## What blocks preflight

For migrations known by the selected immutable Framework revision, preflight requires:

1. every known migration file exists in the project revision;
2. every known migration appears in `control_plane/deploy_manifest.txt`;
3. each manifest path appears only once;
4. known Framework migrations preserve Framework relative order.

A missing manifest itself is blocking.

Example:

```text
001
010
020
030
040
050
060
070
080
```

Moving `080` before `060`, omitting `080`, or listing `080` twice blocks before Snowflake authentication.

## Domain-owned extensions remain allowed

The control plane is domain-owned. A project may add explicit migrations that the Framework does not know about, for example:

```text
control_plane/sql/900_transport_specific_policy.sql
```

Unknown/domain-owned entries are allowed by the Framework readiness gate. The deployment workflow still applies path-safety and file-existence checks to every manifest entry.

Framework-known migrations only need to preserve their Framework relative order at the repository-preflight layer. After a domain has actually applied/baselined migrations in a Snowflake environment, `esf-migrate` additionally locks every recorded path to its exact manifest position and checksum. That stronger environment rule prevents inserting, removing, reordering or editing already-recorded migrations.

## Why not rewrite the manifest

The Framework still does not repair or synchronize the deploy manifest automatically.

```text
missing migration
  -> control-plan reports it
  -> engineer reviews migration and upgrade notes
  -> engineer appends it
  -> preflight becomes READY
```

This preserves the established ownership rule:

```text
Framework may create a missing new ownership unit.
Framework never rewrites an existing domain-owned deployment decision.
```

## Preflight versus migration history

These gates solve different problems.

`esf-control-preflight` reads only the checked-out repository and answers:

```text
Does this Git revision contain the complete current Framework control baseline?
```

`esf-migrate deploy` runs after authentication and answers:

```text
For this exact Snowflake environment, which committed CONTROL/SILVER migration files are new,
which are already recorded with the same checksum, and which must be blocked?
```

An existing populated environment with empty deployment history is not silently treated as fresh. The migration runner detects existing CONTROL/SILVER objects and requires an explicitly reviewed baseline so historical SQL is not replayed during adoption.

See `APPLY_ONCE_MIGRATIONS.md` for baseline, checksum, failure/remediation and concurrency rules.

## Why this is not a runtime engine

Preflight operates only on committed repository files. The migration runner only applies or skips committed SQL files; neither component chooses transformation behavior, generates runtime SQL from metadata, or dynamically routes datasets.

The deployment sequence is explicit:

```text
immutable project revision
  -> contract validation
  -> control-plane preflight
  -> manifest path/file validation
  -> OIDC authentication
  -> bootstrap domain-local DEPLOYMENT_HISTORY
  -> apply/skip committed CONTROL migrations in manifest order
  -> apply/skip committed Silver migrations in manifest order
  -> dbt
```

Scaffolding never runs during deployment. Live verification of actual Stream/Task/procedure/migration behavior remains a separate environment/integration gate once a DEV account and WIF identity are configured.
