from __future__ import annotations

from typing import Any

from .pipeline_model import PipelineNames, _csv, _join


def render_compare_sql(
    pattern: str, names: PipelineNames, contract: dict[str, Any], *, candidate: bool
) -> str:
    if not candidate:
        return (
            f"-- {names.dataset_key} {names.version}: initial implementation has no prior active version to compare.\n"
            "-- Candidate versions generate active-vs-candidate checks in this file.\n"
        )
    if pattern == "custom":
        return (
            f"-- {names.dataset_key} {names.version}: define domain-owned active-vs-candidate comparisons here.\n"
            "-- Write review evidence to CONTROL.VERSION_VALIDATION.\n"
        )
    business_key = [str(value).upper() for value in contract.get("business_key", [])]
    keys = _csv(business_key)
    key_join = _join("A", "C", business_key)
    missing_predicate = " OR ".join(
        [f"A.{business_key[0]} IS NULL", f"C.{business_key[0]} IS NULL"]
    )
    if pattern == "scd2":
        assert names.current_relation and names.history_relation and names.published_current
        assert names.published_history
        active_relation = names.published_current
        candidate_relation = names.current_relation
        history_checks = f"""

INSERT INTO CONTROL.VERSION_VALIDATION (
    VALIDATION_ID, DATASET_ID, ACTIVE_VERSION, CANDIDATE_VERSION,
    CHECK_NAME, STATUS, ACTIVE_VALUE, CANDIDATE_VALUE, DIFFERENCE_VALUE, DETAILS
)
WITH ACTIVE_COUNT AS (
    SELECT COUNT(*) AS N FROM {names.published_history}
),
CANDIDATE_COUNT AS (
    SELECT COUNT(*) AS N FROM {names.history_relation}
)
SELECT
    UUID_STRING(), '{names.dataset_key}',
    (SELECT ACTIVE_VERSION FROM CONTROL.DATASET WHERE DATASET_ID = '{names.dataset_key}'),
    '{names.version}', 'history_row_count',
    IFF(A.N = C.N, 'PASS', 'REVIEW_REQUIRED'),
    TO_VARCHAR(A.N), TO_VARCHAR(C.N), TO_VARCHAR(C.N - A.N),
    OBJECT_CONSTRUCT('note', 'History-count differences can be valid but require review')
FROM ACTIVE_COUNT A CROSS JOIN CANDIDATE_COUNT C;
"""
    else:
        assert names.physical_relation and names.published_relation
        active_relation = names.published_relation
        candidate_relation = names.physical_relation
        history_checks = ""

    return f"""-- Active-vs-candidate evidence. Review before generating/executing cutover SQL.

INSERT INTO CONTROL.VERSION_VALIDATION (
    VALIDATION_ID, DATASET_ID, ACTIVE_VERSION, CANDIDATE_VERSION,
    CHECK_NAME, STATUS, ACTIVE_VALUE, CANDIDATE_VALUE, DIFFERENCE_VALUE, DETAILS
)
WITH ACTIVE_COUNT AS (
    SELECT COUNT(*) AS N FROM {active_relation}
),
CANDIDATE_COUNT AS (
    SELECT COUNT(*) AS N FROM {candidate_relation}
)
SELECT
    UUID_STRING(), '{names.dataset_key}',
    (SELECT ACTIVE_VERSION FROM CONTROL.DATASET WHERE DATASET_ID = '{names.dataset_key}'),
    '{names.version}', 'current_row_count',
    IFF(A.N = C.N, 'PASS', 'REVIEW_REQUIRED'),
    TO_VARCHAR(A.N), TO_VARCHAR(C.N), TO_VARCHAR(C.N - A.N), NULL
FROM ACTIVE_COUNT A CROSS JOIN CANDIDATE_COUNT C;

INSERT INTO CONTROL.VERSION_VALIDATION (
    VALIDATION_ID, DATASET_ID, ACTIVE_VERSION, CANDIDATE_VERSION,
    CHECK_NAME, STATUS, ACTIVE_VALUE, CANDIDATE_VALUE, DIFFERENCE_VALUE, DETAILS
)
WITH A AS (
    SELECT DISTINCT {keys} FROM {active_relation}
),
C AS (
    SELECT DISTINCT {keys} FROM {candidate_relation}
),
DIFF AS (
    SELECT COUNT(*) AS N
    FROM A
    FULL OUTER JOIN C
      ON {key_join}
    WHERE {missing_predicate}
)
SELECT
    UUID_STRING(), '{names.dataset_key}',
    (SELECT ACTIVE_VERSION FROM CONTROL.DATASET WHERE DATASET_ID = '{names.dataset_key}'),
    '{names.version}', 'business_key_coverage',
    IFF(N = 0, 'PASS', 'REVIEW_REQUIRED'),
    NULL, NULL, TO_VARCHAR(N),
    OBJECT_CONSTRUCT('symmetric_key_difference_count', N)
FROM DIFF;

INSERT INTO CONTROL.VERSION_VALIDATION (
    VALIDATION_ID, DATASET_ID, ACTIVE_VERSION, CANDIDATE_VERSION,
    CHECK_NAME, STATUS, ACTIVE_VALUE, CANDIDATE_VALUE, DIFFERENCE_VALUE, DETAILS
)
WITH DUPLICATES AS (
    SELECT COUNT(*) AS N
    FROM (
        SELECT {keys}
        FROM {candidate_relation}
        GROUP BY {keys}
        HAVING COUNT(*) > 1
    )
)
SELECT
    UUID_STRING(), '{names.dataset_key}',
    (SELECT ACTIVE_VERSION FROM CONTROL.DATASET WHERE DATASET_ID = '{names.dataset_key}'),
    '{names.version}', 'candidate_business_key_uniqueness',
    IFF(N = 0, 'PASS', 'FAIL'),
    NULL, NULL, TO_VARCHAR(N), NULL
FROM DUPLICATES;{history_checks}
"""
