from __future__ import annotations

from collections.abc import Sequence


IDEMPOTENCY_DECLARATIONS = """    V_IDEMPOTENCY_CONFLICTS NUMBER DEFAULT 0;
    E_IDEMPOTENCY_CONFLICT EXCEPTION (
        -20040,
        'Incoming rows share an idempotency identity but disagree on payload.'
    );
"""


def _qualified(alias: str, columns: Sequence[str]) -> str:
    return ", ".join(f"{alias}.{column}" for column in columns)


def render_idempotency_conflict_guard(
    relation: str,
    *,
    identity_columns: Sequence[str],
    payload_columns: Sequence[str],
    alias: str = "I",
) -> str:
    """Fail closed when one reviewed identity maps to conflicting payloads in one input batch."""
    if not identity_columns:
        raise ValueError("idempotency identity must contain at least one column")
    if not payload_columns:
        raise ValueError("idempotency payload must contain at least one column")
    identity = _qualified(alias, identity_columns)
    payload = _qualified(alias, payload_columns)
    return f"""        V_IDEMPOTENCY_CONFLICTS := (
            SELECT COUNT(*)
            FROM (
                SELECT {identity}
                FROM {relation} {alias}
                GROUP BY {identity}
                HAVING COUNT(DISTINCT TO_VARCHAR(HASH({payload}))) > 1
            ) CONFLICTING_IDENTITIES
        );
        IF (V_IDEMPOTENCY_CONFLICTS > 0) THEN
            RAISE E_IDEMPOTENCY_CONFLICT;
        END IF;

"""


def render_deduped_relation(
    relation: str,
    *,
    identity_columns: Sequence[str],
    payload_columns: Sequence[str],
    output_alias: str,
) -> str:
    """Collapse exact duplicate rows after conflict detection has proved payload agreement."""
    if not identity_columns:
        raise ValueError("idempotency identity must contain at least one column")
    if not payload_columns:
        raise ValueError("idempotency payload must contain at least one column")
    identity = _qualified("D", identity_columns)
    payload = _qualified("D", payload_columns)
    return f"""(
            SELECT D.*
            FROM {relation} D
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY {identity}
                ORDER BY TO_VARCHAR(HASH({payload}))
            ) = 1
        ) {output_alias}"""
