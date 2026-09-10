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
  -> read-only CI gate
  -> non-zero exit when the current Framework control baseline is not deployable
```

The reusable project deployment workflow runs `esf-control-preflight --project-root project` before requesting a Snowflake OIDC token.

## What blocks deployment

For migrations known by the selected immutable Framework revision, preflight requires:

1. every known migration file exists in the project revision;
2. every known migration appears in `control_plane/deploy_manifest.txt`;
3. each manifest path appears only once;
4. known Framework migrations preserve Framework order.

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

Unknown/domain-owned entries are allowed by the Framework readiness gate. The existing deployment workflow still applies its path-safety and file-existence checks to every manifest entry.

Framework-known migrations only need to preserve their relative order. Domain-owned migrations can be positioned by the domain where their explicit dependencies require.

## Why not rewrite the manifest

The Framework still does not repair or synchronize the deploy manifest automatically.

```text
missing migration
  -> control-plan reports it
  -> engineer reviews migration and upgrade notes
  -> engineer appends it in the correct place
  -> preflight becomes READY
```

This preserves the established ownership rule:

```text
Framework may create a missing new ownership unit.
Framework never rewrites an existing domain-owned deployment decision.
```

## Why this is not a runtime engine

Preflight operates only on committed repository files. It does not query Snowflake, inspect deployed objects, choose transformation behavior, or dynamically route datasets.

The deployment sequence stays explicit:

```text
immutable project revision
  -> contract validation
  -> control-plane preflight
  -> manifest path/file validation
  -> OIDC authentication
  -> committed CONTROL SQL in manifest order
  -> committed Silver SQL in manifest order
  -> dbt
```

Live verification of the actual Snowflake objects remains a separate environment/integration gate once a DEV account and WIF identity are configured.
