from __future__ import annotations

from pathlib import Path
from typing import Any

_BOOTSTRAP_ARCHETYPES = {
    "watermark",
    "net_change",
    "full_change",
    "cursor_or_file",
}
_HANDOFF_CHECKPOINT_KINDS = {
    "watermark",
    "cursor",
    "source_position",
    "event_offset",
}


def validate_bootstrap_metadata(contract: dict[str, Any], path: Path) -> list[str]:
    """Validate the bounded initial-snapshot -> incremental handoff contract.

    Source-specific extraction mechanics intentionally remain outside this
    validator. The reusable contract only accepts handoffs whose steady-state
    source position and overlap semantics are explicit enough to fail closed.
    """
    capture = contract.get("capture")
    if not capture:
        return []

    bootstrap = capture.get("bootstrap")
    if not bootstrap:
        return []

    errors: list[str] = []
    archetype = capture["archetype"]
    checkpoint_kind = capture["checkpoint_kind"]
    incremental_start = bootstrap["incremental_start"]

    if archetype not in _BOOTSTRAP_ARCHETYPES:
        errors.append(
            f"{path}: capture.bootstrap snapshot_then_incremental is not valid for "
            f"capture.archetype={archetype}"
        )

    if checkpoint_kind not in _HANDOFF_CHECKPOINT_KINDS:
        allowed = ", ".join(sorted(_HANDOFF_CHECKPOINT_KINDS))
        errors.append(
            f"{path}: capture.bootstrap requires a resumable steady-state handoff checkpoint; "
            f"checkpoint_kind={checkpoint_kind}, allowed: {allowed}"
        )

    if incremental_start == "inclusive_with_deduplication" and not capture.get(
        "idempotency_columns"
    ):
        errors.append(
            f"{path}: inclusive bootstrap handoff requires capture.idempotency_columns "
            "so boundary overlap can be replayed deterministically"
        )

    if contract["change_semantics"]["mode"] == "snapshot":
        errors.append(
            f"{path}: capture.bootstrap describes a transition to an incremental source; "
            "raw change_semantics.mode must not remain snapshot"
        )

    return errors
