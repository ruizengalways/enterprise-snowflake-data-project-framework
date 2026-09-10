# Release Readiness and Audit

## Goal

A candidate deployment is not a production release. The Framework keeps those concerns separate:

```text
candidate deployment
  -> candidate runtime evidence
  -> candidate DQ evidence
  -> active-vs-candidate comparison
  -> release preflight
  -> explicit engineer-run cutover
  -> release postflight
  -> RELEASE_RUN audit
```

The release layer consumes evidence that already exists. It does not infer business correctness, auto-approve a candidate, auto-run production SQL, or introduce a runtime metadata router.

## Version invariants

`CONTROL.DATASET_VERSION_INVARIANT_V` makes the current two-pointer model fail-closed without introducing a speculative lifecycle state machine.

For one logical dataset:

```text
ACTIVE_VERSION is non-null
exactly one DATASET_VERSION row has STATUS = ACTIVE
that ACTIVE row matches ACTIVE_VERSION
at most one DATASET_VERSION row has STATUS = DEPLOYED
CANDIDATE_VERSION != ACTIVE_VERSION
CANDIDATE_VERSION NULL <=> no DEPLOYED candidate row
CANDIDATE_VERSION non-NULL => exactly one matching DEPLOYED row
candidate must not point to RETIRED
```

Candidate registration also checks the current environment before changing the pointer. Registering v3 while v2 is already the candidate fails before `DATASET.CANDIDATE_VERSION` can be overwritten.

## Readiness evidence

`CONTROL.RELEASE_READINESS_V` combines only operational evidence needed to decide whether a cutover may be reviewed:

- version-pointer/status invariants;
- latest candidate runtime evidence;
- latest candidate DQ evidence;
- latest active-vs-candidate comparison evidence.

`CONTROL.VERSION_RUNTIME_STATUS_V` normalizes evidence per implementation version without turning Tasks, batch SQL, or Dynamic Tables into one runtime engine. Explicit Stream/Task and batch implementations use `CONTROL.PIPELINE_RUN`; Dynamic Tables use native refresh history through `CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V`. `CONTROL.CANDIDATE_RUNTIME_STATUS_V` is only the candidate-filtered surface used by release readiness.

The result is one of:

```text
READY
  no hard failure and no review-only evidence remains

REVIEW_REQUIRED
  no hard failure, but WARN DQ or review-only comparison evidence needs human acceptance

BLOCKED
  invariant failure, missing/failed runtime evidence, missing/failed DQ,
  stale DQ/comparison, or missing/failed comparison evidence
```

`REVIEW_REQUIRED` is deliberately not PASS. `BLOCKED` has no override path.

DQ and every latest comparison check must be at least as new as the latest candidate runtime evidence. The comparison summary tracks both the newest and oldest latest-check timestamps so rerunning one check cannot hide another stale check. Candidate catch-up/refresh therefore happens before release preflight. A cutover must not create a new transformation run after accepted DQ/comparison evidence and then publish it without revalidation.

## Generated release ownership unit

`esf release-sql` produces a reviewable directory:

```text
README.md
preflight.sql
activate.sql
rollback.sql
postflight.sql
```

`preflight.sql` is read-only. `activate.sql` repeats the readiness check immediately before mutation; a stale preview cannot authorize a later release.

The activate script also requires the requested edge to match the live environment:

```text
DATASET.ACTIVE_VERSION    = requested from_version
DATASET.CANDIDATE_VERSION = requested to_version
```

Stable published views still switch with `CREATE OR REPLACE VIEW ... COPY GRANTS`. Version status changes are made together, the dataset pointer then changes, and the previous runtime is retired last.

Postflight checks the stable view definition with an identifier-boundary regular-expression match, so a target such as `V2` cannot be falsely accepted merely because a different relation such as `V20` contains the same prefix.

## Release audit

Migration 120 creates `CONTROL.RELEASE_RUN`. Each engineer-run activate or rollback attempt records:

```text
release id
dataset / action / from / to
STARTED / SUCCEEDED / FAILED
preflight status and reason
cutover timestamp
postflight status and reason
failed phase
operator user / role / warehouse
review-only acceptance and reason
Snowflake error code / message
```

The script records failures and re-raises the Snowflake error. The ledger is evidence; it is not an orchestrator.

## Postflight

Activation succeeds only after checking that:

```text
DATASET.ACTIVE_VERSION = target
DATASET.CANDIDATE_VERSION IS NULL
exactly one version row is ACTIVE
target row is ACTIVE
prior row is RETIRED
stable published view definition references target physical relation
```

`postflight.sql` exposes the latest audit record, invariant view and version rows for operator review.

Snowflake DDL is not treated as one rollbackable transaction. A failed postflight is therefore explicit evidence that state must be inspected and corrected; the Framework does not blindly retry a partially applied cutover.

## Rollback boundary

A generated rollback is tied to the release edge that produced it. It fails closed if a newer candidate is registered after cutover. This prevents an old rollback file from silently overwriting a newer release cycle.

Rollback also does not pretend that `RESUME` or `REFRESH` proves the previous implementation has caught up. Before running the rollback operation, the operator must explicitly catch up the retired target implementation and run its DQ after that latest target runtime evidence. The rollback hard preflight then requires:

```text
expected current active version
no newer candidate pointer
exactly one ACTIVE version row
rollback target is RETIRED
rollback target runtime status = SUCCESS
rollback target DQ status = PASS
target DQ timestamp >= target runtime evidence timestamp
if comparable data timestamps exist: target DATA_MAX_AT >= current active DATA_MAX_AT
otherwise: target runtime evidence timestamp >= current active runtime evidence timestamp
```

There is no generated bypass for this rollback gate. If the framework cannot establish that the old target was explicitly caught up and revalidated, it blocks instead of republishing stale data.

## What this design does not add

This feature intentionally does not add:

- DEVELOPMENT / BOOTSTRAPPING / SHADOW / VALIDATED lifecycle states;
- automatic release approval;
- automatic production execution;
- dynamic SQL routing from metadata;
- a common runtime engine for Tasks and Dynamic Tables;
- a second enterprise-wide writable control plane.

The existing `ACTIVE_VERSION` / `CANDIDATE_VERSION` model remains until real operational evidence justifies a richer lifecycle.
