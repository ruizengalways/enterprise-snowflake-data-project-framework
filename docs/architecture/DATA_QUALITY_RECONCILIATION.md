# Data quality and reconciliation evidence

## Position

Operational health must answer both:

```text
Did the pipeline run?
Is the published data structurally/operationally acceptable?
```

Run success and SLA freshness are not enough. A task can succeed while producing duplicate keys, overlapping SCD2 history, or a source/Bronze mismatch.

The Framework therefore standardizes domain-local DQ/reconciliation **evidence**, while keeping the checks themselves explicit and dataset-owned.

## Boundary

```text
dataset-local validation SQL
        -> CONTROL.DQ_RESULT

source/ingestion/domain reconciliation SQL
        -> CONTROL.RECONCILIATION_RESULT

CONTROL
        -> latest-status views
        -> quality incidents
        -> DATASET_HEALTH_V
        -> enterprise read-only export
```

The Control Plane does not store a table of generic DQ expressions and does not dynamically execute rules from metadata.

## Dataset-local DQ

For the four standard Silver patterns, scaffolded `020_validate.sql` defines a version-local validation procedure. The initial structural checks are intentionally small and explainable:

```text
append
  - duplicate RAW-contract idempotency key
  - NULL business key

scd1
  - duplicate business key
  - NULL business key

full_refresh
  - duplicate business key
  - NULL business key

scd2
  - multiple active rows per business key
  - NULL business key
  - overlapping effective periods
```

These are starter invariants, not a universal business DQ library. After creation, the domain can add/remove checks in the committed dataset-local SQL.

Each normal pipeline Task runs:

```text
CALL dataset APPLY procedure
CALL dataset VALIDATE procedure
```

Validation inserts one normalized result row per check into `CONTROL.DQ_RESULT`. A failed check is recorded as evidence; the default starter does not automatically fail the transformation Task. A domain may explicitly raise an exception for a hard-stop rule when that behavior is required.

`020_validate.sql` is now part of the committed deployment fragment so the validation procedure exists before the Task is created.

## Active vs candidate versions

DQ evidence is versioned.

```text
v1 ACTIVE    -> participates in production DATASET_HEALTH
v2 CANDIDATE -> retained for shadow/release review only
```

A failing candidate must not make a healthy active production dataset red. After v2 becomes active, its latest DQ run becomes the health evidence for the logical dataset.

## Reconciliation

Reconciliation is deliberately not auto-generated because valid comparisons depend on the ingestion/pattern/business semantics.

For example, row counts may legitimately differ because of:

- deduplication;
- SCD2 history expansion;
- delete/tombstone handling;
- filtering;
- business-grain changes.

Migration 080 supplies a stable evidence API:

```text
CONTROL.RECONCILIATION_RESULT
CONTROL.RECORD_RECONCILIATION_RESULT(...)
```

Domain-owned code computes the comparison and records:

```text
dataset
version (optional)
stage
check id
severity
PASS / FAIL
source value
target value
difference value
details
```

Versionless results are appropriate for boundaries such as Source -> Bronze. Version-specific results are appropriate where a Silver implementation version matters.

## Status normalization

Check severity has two intended operational classes:

```text
ERROR -> failure contributes RED health and automatic incident
WARN  -> failure contributes YELLOW health but no automatic failure incident
```

Latest DQ status:

```text
FAILED
WARNING
PASS
UNASSESSED
```

Latest reconciliation status uses the same shape.

## Incident lifecycle

`CONTROL.EVALUATE_QUALITY_INCIDENTS()` manages only normalized quality conditions:

```text
DQ_FAILURE
RECONCILIATION_FAILURE
```

It does not manage ingestion/pipeline/dbt/SLA conditions; those remain in the existing domain evaluator.

The quality evaluator follows the same incident model:

```text
first active failure -> OPEN
continued failure    -> update same incident key
new successful evidence -> RESOLVED
```

Only active-production DQ failures participate in automatic DQ incidents. Reconciliation chooses the latest relevant active-version or versionless evidence per stage.

The one-minute serverless `CONTROL.EVALUATE_QUALITY_INCIDENTS_TASK` is created suspended. Resume it explicitly after migration review, just like the existing health task.

## Dashboard contract

Migration 080 extends `CONTROL.DATASET_HEALTH_V` with:

```text
DQ_STATUS
RECONCILIATION_STATUS
LAST_DQ_AT
LAST_RECONCILIATION_AT
```

Overall status is derived from the existing base health plus quality evidence:

```text
base RED or DQ/reconciliation ERROR failure -> RED
base YELLOW or quality WARN failure         -> YELLOW
otherwise                                    -> base health
```

Lifecycle still wins:

```text
DECOMMISSIONED
PAUSED
```

The enterprise read-only export carries these additional fields. Enterprise monitoring still does not recalculate DQ, SLA, or health.

## Repair relationship

DQ/reconciliation evidence identifies the failing boundary; repair remains layer-aware:

```text
Gold wrong / Silver correct
  -> rebuild dbt descendants

Silver wrong / Bronze correct
  -> candidate version + replay/rebuild

Bronze wrong
  -> repair ingestion/backfill first
```

The Framework does not introduce an autonomous repair engine.

## Guardrails

Continue to reject:

- generic rule expressions stored in CONTROL and dynamically executed;
- auto-generated business DQ rules;
- naive universal row-count reconciliation;
- candidate DQ failures poisoning active production health;
- automatic mutation of production data after a failed check;
- cross-domain writes for enterprise monitoring.
