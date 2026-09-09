# Project creation and ownership lifecycle

## Ownership model

The Framework is a project creation toolkit, not a runtime dependency.

```text
Framework
  -> initializes repository structure
  -> adds source-system boundaries
  -> creates starter dataset source once
  -> validates static contracts

Domain repository
  -> reviews and commits generated source
  -> edits implementation directly
  -> owns deployment order
  -> remains the only production source of truth
```

## Non-destructive operations

`esf init-project` creates missing project skeleton directories/files and never replaces an existing file.

`esf add-source <source>` is conservative: if any path that represents that source already exists, it reports `already exists` and makes no changes.

`esf plan --source <source>` is read-only.

`esf scaffold` and `esf scaffold-all` use dataset-directory existence as the ownership handoff boundary. Existing dataset directories are never updated, repaired, or normalized by the Framework.

## Deployment boundary

Scaffolding is a developer-time action only:

```text
developer scaffold
  -> generated source committed
  -> PR review
  -> merge
  -> CI/CD executes committed source
```

Deployment must never run `esf scaffold` or regenerate SQL from source manifests.
