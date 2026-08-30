from __future__ import annotations

from pathlib import Path
from typing import Any

SCD2_STRATEGIES = {
    "scd2_snapshot",
    "scd2_merge",
    "scd2_stream_task",
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

    if dataset_keys != contract_keys:
        errors.append(
            f"{path}: dataset.business_key must exactly match raw contract business_key; "
            f"dataset={dataset_keys}, contract={contract_keys}"
        )

    effective_at = scd2["effective_at_column"]
    order_columns = scd2["order_columns"]
    tracked_columns = scd2["tracked_columns"]
    operation_column = scd2.get("operation_column")
    delete_values = scd2.get("delete_values", [])

    referenced = [effective_at, *order_columns, *tracked_columns]
    if operation_column:
        referenced.append(operation_column)
    undeclared = sorted({name for name in referenced if name not in declared_columns})
    if undeclared:
        errors.append(
            f"{path}: dataset.scd2 references columns not declared by raw contract: {', '.join(undeclared)}"
        )

    if effective_at not in order_columns:
        errors.append(
            f"{path}: dataset.scd2.effective_at_column must be included in dataset.scd2.order_columns"
        )

    tracked_keys = [name for name in tracked_columns if name in contract_keys]
    if tracked_keys:
        errors.append(
            f"{path}: dataset.scd2.tracked_columns must describe attributes, not business keys: "
            f"{', '.join(tracked_keys)}"
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

    if delete_values and not operation_column:
        errors.append(f"{path}: dataset.scd2.delete_values requires dataset.scd2.operation_column")
    if operation_column and not delete_values:
        errors.append(f"{path}: dataset.scd2.operation_column requires dataset.scd2.delete_values")

    change_semantics = contract["change_semantics"]
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
