# Reconciliation

Reconciliation answers whether two pipeline boundaries agree closely enough for a specific operational expectation. The Framework standardizes **evidence**, not the business rule.

Examples include:

- source count vs Bronze count for a completed batch;
- Bronze event count vs Silver accepted-event count;
- key coverage between two layers;
- amount/control-total comparison;
- expected file count vs loaded file count.

Do not assume raw row counts should always match. SCD2 history, deduplication, deletes, filtering and business-grain changes can make naive count equality invalid.

## Evidence contract

Migration 080 provides:

```text
CONTROL.RECONCILIATION_RESULT
CONTROL.RECORD_RECONCILIATION_RESULT(...)
CONTROL.RECONCILIATION_LATEST_STAGE_V
CONTROL.RECONCILIATION_ACTIVE_STAGE_V
```

A domain-owned ingestion, Silver validation, or operational script decides what to compare, computes the values, and records a normalized `PASS`/`FAIL` result.

Example:

```sql
CALL CONTROL.RECORD_RECONCILIATION_RESULT(
    'batch_20260910_001',
    'fleet_mssql.customer',
    NULL,
    'SOURCE_TO_BRONZE',
    'batch_row_count',
    'ERROR',
    'PASS',
    '12839291',
    '12839291',
    '0',
    OBJECT_CONSTRUCT('source_batch_id', '20260910_001')
);
```

Use `VERSION = NULL` when the evidence belongs to a non-versioned boundary such as Source -> Bronze. Use the concrete implementation version when the reconciliation is about a versioned Silver implementation.

For the same stage, active-version evidence takes precedence over versionless evidence. Recency is considered within that precedence. This prevents a newer generic/unversioned check from masking the current Silver implementation's reconciliation result.

## Fail-closed normalization

The record API intentionally accepts a very small operational vocabulary:

```text
severity: ERROR | WARN
status:   PASS | FAIL
```

Unknown severity is normalized to `ERROR`. Unknown status is stored as `INVALID`. Any status other than `PASS` participates as a failure, so malformed producer values cannot silently become healthy evidence.

## Health behavior

The domain health contract considers the latest relevant reconciliation per stage. An active-version/error-severity failure contributes `RECONCILIATION_STATUS = FAILED`, turns the dataset health red, and the quality-incident evaluator maintains one open `RECONCILIATION_FAILURE` incident per dataset/stage until newer successful evidence recovers it.

`WARN` failures contribute a yellow warning but do not open an automatic failure incident.

Candidate-version evidence is retained for release review but does not make the currently active production dataset unhealthy.

The serverless quality-incident task is created suspended. Resume it explicitly after migration review. Migration 080 does not replace the existing domain-health task.

## Repair

Reconciliation tells you **where the boundaries disagree**; it does not decide the repair automatically.

```text
Source -> Bronze mismatch
  -> repair ingestion/backfill first

Bronze correct, Silver mismatch
  -> candidate version + replay/rebuild

Silver correct, Gold mismatch
  -> rebuild affected dbt descendants
```

Keep replay, backfill and reset distinct. Do not use a reconciliation script to silently mutate production data.
