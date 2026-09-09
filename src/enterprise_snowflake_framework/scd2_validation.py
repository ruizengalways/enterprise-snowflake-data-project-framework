from __future__ import annotations

from pathlib import Path
from typing import Any


def validate_scd2_metadata(dataset: dict[str, Any], contract: dict[str, Any], path: Path) -> list[str]:
    """Validate SCD2 correctness links to a source contract using only v2 metadata."""
    load = dataset.get("load")
    if not load or load["strategy"] != "scd2":
        return []

    scd2 = load["scd2"]
    errors: list[str] = []
    declared_columns = {column["name"] for column in contract["columns"]}
    dataset_keys = load["business_key"]
    contract_keys = contract["business_key"]

    if dataset_keys != contract_keys:
        errors.append(
            f"{path}: load.business_key must exactly match raw contract business_key; "
            f"dataset={dataset_keys}, contract={contract_keys}"
        )

    referenced = [scd2["effective_at_column"], *scd2["order_columns"], *scd2["tracked_columns"]]
    delete = scd2.get("delete")
    if delete:
        referenced.append(delete["operation_column"])
    undeclared = sorted({name for name in referenced if name not in declared_columns})
    if undeclared:
        errors.append(f"{path}: load.scd2 references undeclared raw columns: {', '.join(undeclared)}")

    tracked_keys = [name for name in scd2["tracked_columns"] if name in contract_keys]
    if tracked_keys:
        errors.append(
            f"{path}: load.scd2.tracked_columns must be attributes, not business keys: {', '.join(tracked_keys)}"
        )

    if scd2["effective_at_column"] not in scd2["order_columns"]:
        errors.append(f"{path}: load.scd2.effective_at_column must be present in order_columns")

    missing_source_order = [
        name for name in contract.get("ordering_columns", []) if name not in scd2["order_columns"]
    ]
    if missing_source_order:
        errors.append(
            f"{path}: load.scd2.order_columns must include raw contract ordering columns: "
            f"{', '.join(missing_source_order)}"
        )

    missing_idempotency = [
        name for name in contract.get("idempotency_key", [])
        if name not in contract_keys and name not in scd2["order_columns"]
    ]
    if missing_idempotency:
        errors.append(
            f"{path}: load.scd2.order_columns must include non-key idempotency columns: "
            f"{', '.join(missing_idempotency)}"
        )

    if dataset["materialization"]["type"] != "snapshot":
        fidelity = contract.get("capture_fidelity")
        if fidelity not in {"full_change", "full_event"}:
            errors.append(
                f"{path}: authoritative event-history SCD2 requires capture_fidelity "
                f"full_change/full_event; got {fidelity!r}"
            )

    change_semantics = contract["change_semantics"]
    if change_semantics.get("delete_semantics") == "tombstone":
        expected_column = change_semantics.get("operation_column")
        expected_values = change_semantics.get("delete_values", [])
        if not delete:
            errors.append(f"{path}: tombstone SCD2 requires load.scd2.delete")
        else:
            if delete["operation_column"] != expected_column:
                errors.append(f"{path}: tombstone SCD2 must use raw operation_column {expected_column!r}")
            if set(delete["values"]) != set(expected_values):
                errors.append(f"{path}: tombstone SCD2 delete values must match raw contract delete_values")

    return errors
