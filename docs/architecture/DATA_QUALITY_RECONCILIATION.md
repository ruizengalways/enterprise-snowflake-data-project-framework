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

`020_validate.sql` is part of the committed deployment fragment so the validation procedure exists before the Task is created.

## Active vs candidate versions

DQ evidence is versioned.

```text
v1 ACTIVE    -> participates in production DATASET_HEALTH
v2 CANDIDATE -> retained for shadow/release review only
```

A failing candidate must not make a healthy active production dataset red. After v2 becomes active, its latest DQ run becomes the health evidence for the logical dataset.

Release remains explicit. Candidate DQ evidence is one input to engineer review; the Framework does not automatically approve or cut over a version.

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

For the same dataset/stage, active-version reconciliation evidence takes precedence over unversioned evidence. Recency is then used within that precedence. This prevents a newer generic result from masking evidence for the currently active Silver implementation.

## Fail-closed status normalization

The evidence contract intentionally stays small:

```text
severity: ERROR | WARN
status:   PASS | FAIL
```

The record procedures normalize unknown severity to `ERROR` and unknown status to `INVALID`. Latest-status views treat any status other than `PASS` as a failure. Malformed producer values therefore cannot silently become healthy evidence.

Operational interpretation is:

```text
ERROR failure -> RED health and automatic failure incident
WARN failure  -> YELLOW health, no automatic failure incident
```

Latest DQ/reconciliation status uses:

```text
FAILED
WARNING
PASS
UNASSESSED
```

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

Only active-production DQ failures participate in automatic DQ incidents. Reconciliation uses the active-version/versionless precedence described above.

The one-minute serverless `CONTROL.EVALUATE_QUALITY_INCIDENTS_TASK` is created suspended. It is deliberately separate from the existing domain-health task so adopting migration 080 cannot replace or silently suspend a task that an existing domain already operates. Resume it explicitly after migration review.

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

The enterprise read-only export carries the additional quality fields. Enterprise monitoring still does not recalculate DQ, reconciliation, SLA, or health.

Because migration 080 extends the export schema, cross-domain `SELECT * UNION ALL` consumers must coordinate rollout across participating domains. During staggered upgrades, select an explicit common column set centrally.

## Evidence detail

`CONTROL.DATASET_QUALITY_STATUS_V` is the one-row-per-dataset operational summary. `CONTROL.DATASET_QUALITY_DETAIL_V` is the inspectable evidence surface combining raw DQ and reconciliation results. It is not a rule catalog and contains no executable rule SQL.

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
- malformed evidence values silently counting as success;
- automatic mutation of production data after a failed check;
- cross-domain writes for enterprise monitoring.
