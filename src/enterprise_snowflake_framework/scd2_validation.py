from __future__ import annotations

from pathlib import Path
from typing import Any

SCD2_STRATEGIES = {
    "scd2_snapshot",
    "scd2_merge",
    "scd2_stream_task",
}
EVENT_SCD2_STRATEGIES = {
    "scd2_merge",
    "scd2_stream_task",
}
_EVENT_ONLY_FIELDS = {
    "effective_at_column",
    "order_columns",
    "operation_column",
    "delete_values",
    "late_arriving_policy",
}


def validate_scd2_metadata(
    dataset: dict[str, Any],
    contract: dict[str, Any],
    path: Path,
) -> list[str]:
    """Validate semantic links between dataset SCD2 metadata and its RAW contract."""
    strategy = dataset["load_strategy"]
    scd2 = dataset.get("scd2")

    if strategy not in SCD2_STRATEGIES:
        if scd2 is not None:
            return [f"{path}: dataset.scd2 is valid only for an SCD2 load strategy"]
        return []

    # JSON Schema reports a clearer missing-field error when this is absent.
    if not scd2:
        return []

    errors: list[str] = []
    declared_columns = {column["name"] for column in contract["columns"]}
    dataset_keys = dataset.get("business_key", [])
    contract_keys = contract["business_key"]
    tracked_columns = scd2["tracked_columns"]
    change_semantics = contract["change_semantics"]

    if dataset_keys != contract_keys:
        errors.append(
            f"{path}: dataset.business_key must exactly match raw contract business_key; "
            f"dataset={dataset_keys}, contract={contract_keys}"
        )

    undeclared_tracked = sorted({name for name in tracked_columns if name not in declared_columns})
    if undeclared_tracked:
        errors.append(
            f"{path}: dataset.scd2 references columns not declared by raw contract: "
            f"{', '.join(undeclared_tracked)}"
        )

    tracked_keys = [name for name in tracked_columns if name in contract_keys]
    if tracked_keys:
        errors.append(
            f"{path}: dataset.scd2.tracked_columns must describe attributes, not business keys: "
            f"{', '.join(tracked_keys)}"
        )

    if strategy == "scd2_snapshot":
        event_only = sorted(field for field in _EVENT_ONLY_FIELDS if field in scd2)
        if event_only:
            errors.append(
                f"{path}: scd2_snapshot must not declare event-history-only fields: "
                f"{', '.join(event_only)}"
            )
        if change_semantics.get("mode") != "snapshot":
            errors.append(
                f"{path}: scd2_snapshot requires raw change_semantics.mode=snapshot"
            )
        if change_semantics.get("delete_semantics") != "inferred_snapshot_diff":
            errors.append(
                f"{path}: scd2_snapshot requires raw change_semantics.delete_semantics=inferred_snapshot_diff"
            )
        return errors

    if strategy not in EVENT_SCD2_STRATEGIES:
        return errors

    effective_at = scd2["effective_at_column"]
    order_columns = scd2["order_columns"]
    operation_column = scd2.get("operation_column")
    delete_values = scd2.get("delete_values", [])

    referenced_event_columns = [effective_at, *order_columns]
    if operation_column:
        referenced_event_columns.append(operation_column)
    undeclared_event = sorted({name for name in referenced_event_columns if name not in declared_columns})
    if undeclared_event:
        errors.append(
            f"{path}: dataset.scd2 references columns not declared by raw contract: "
            f"{', '.join(undeclared_event)}"
        )

    if effective_at not in order_columns:
        errors.append(
            f"{path}: dataset.scd2.effective_at_column must be included in dataset.scd2.order_columns"
        )

    capture = contract.get("capture") or {}
    missing_capture_order = [
        name for name in capture.get("ordering_columns", []) if name not in order_columns
    ]
    if missing_capture_order:
        errors.append(
            f"{path}: dataset.scd2.order_columns must include raw capture ordering columns: "
            f"{', '.join(missing_capture_order)}"
        )

    # The history macro partitions by business key. Any remaining columns that
    # make a captured event idempotently identifiable must therefore participate
    # in the within-key ordering, otherwise two distinct events can tie.
    non_key_idempotency_columns = [
        name for name in capture.get("idempotency_columns", []) if name not in contract_keys
    ]
    missing_idempotency_order = [
        name for name in non_key_idempotency_columns if name not in order_columns
    ]
    if missing_idempotency_order:
        errors.append(
            f"{path}: dataset.scd2.order_columns must include non-key raw idempotency columns "
            f"for deterministic within-key ordering: {', '.join(missing_idempotency_order)}"
        )

    if delete_values and not operation_column:
        errors.append(f"{path}: dataset.scd2.delete_values requires dataset.scd2.operation_column")
    if operation_column and not delete_values:
        errors.append(f"{path}: dataset.scd2.operation_column requires dataset.scd2.delete_values")

    raw_operation_column = change_semantics.get("operation_column")
    delete_semantics = change_semantics.get("delete_semantics", "none")
    if delete_semantics == "tombstone":
        if operation_column != raw_operation_column:
            errors.append(
                f"{path}: tombstone SCD2 must use raw contract operation_column {raw_operation_column!r}"
            )
        if not delete_values:
            errors.append(f"{path}: tombstone SCD2 requires dataset.scd2.delete_values")

    return errors
