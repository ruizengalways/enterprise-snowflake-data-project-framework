from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

SCHEMA_FILES = {
    "project": "project.schema.json",
    "dataset": "dataset.schema.json",
    "raw_contract": "raw_contract.schema.json",
}
_KEYED_STRATEGIES = {
    "incremental_merge",
    "scd2_snapshot",
    "scd2_merge",
    "scd2_stream_task",
}
_CAPTURE_FIDELITY = {
    "snapshot": {"current_state"},
    "watermark": {"current_state"},
    "net_change": {"net_change"},
    "full_change": {"full_change", "full_event"},
    "snapshot_diff": {"net_change"},
    "cursor_or_file": {"current_state", "net_change", "full_change", "full_event"},
}
_CAPTURE_CHECKPOINTS = {
    "snapshot": {"snapshot_id"},
    "watermark": {"watermark"},
    "net_change": {"watermark", "cursor", "source_position", "event_offset"},
    "full_change": {"cursor", "source_position", "event_offset"},
    "snapshot_diff": {"snapshot_id"},
    "cursor_or_file": {"cursor", "file_identity", "source_position", "event_offset"},
}


class MetadataValidationError(ValueError):
    pass


def load_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise MetadataValidationError(f"{path}: document root must be an object")
    return value


def load_schema(schema_dir: Path, kind: str) -> dict[str, Any]:
    return json.loads((schema_dir / SCHEMA_FILES[kind]).read_text(encoding="utf-8"))


def schema_errors(document: dict[str, Any], schema: dict[str, Any], path: Path) -> list[str]:
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{path}: {location}: {error.message}")
    return errors


def validate_raw_contract(document: dict[str, Any], path: Path) -> list[str]:
    contract = document["contract"]
    columns = contract["columns"]
    names = [column["name"] for column in columns]
    errors: list[str] = []

    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"{path}: contract.columns contains duplicate names: {', '.join(duplicates)}")

    column_names = set(names)
    columns_by_name = {column["name"]: column for column in columns}
    missing_keys = [name for name in contract["business_key"] if name not in column_names]
    if missing_keys:
        errors.append(f"{path}: business_key columns missing from columns: {', '.join(missing_keys)}")
    nullable_keys = [
        name
        for name in contract["business_key"]
        if name in columns_by_name and columns_by_name[name].get("nullable") is True
    ]
    if nullable_keys:
        errors.append(f"{path}: business_key columns must be nullable=false: {', '.join(nullable_keys)}")

    source_timestamp = contract.get("source_timestamp")
    if source_timestamp and source_timestamp not in column_names:
        errors.append(f"{path}: source_timestamp column is not declared: {source_timestamp}")

    changes = contract["change_semantics"]
    if changes["mode"] == "cdc":
        for field in ("operation_column", "sequence_column"):
            column = changes.get(field)
            if not column:
                errors.append(f"{path}: CDC contract requires change_semantics.{field}")
            elif column not in column_names:
                errors.append(f"{path}: {field} column is not declared: {column}")

    capture = contract.get("capture")
    if capture:
        archetype = capture["archetype"]
        fidelity = capture["fidelity"]
        checkpoint_kind = capture["checkpoint_kind"]

        if fidelity not in _CAPTURE_FIDELITY[archetype]:
            allowed = ", ".join(sorted(_CAPTURE_FIDELITY[archetype]))
            errors.append(
                f"{path}: capture archetype {archetype} does not support fidelity {fidelity}; allowed: {allowed}"
            )

        if checkpoint_kind not in _CAPTURE_CHECKPOINTS[archetype]:
            allowed = ", ".join(sorted(_CAPTURE_CHECKPOINTS[archetype]))
            errors.append(
                f"{path}: capture archetype {archetype} does not support checkpoint_kind {checkpoint_kind}; "
                f"allowed: {allowed}"
            )

        lookback = capture.get("lookback_minutes")
        if lookback is not None and archetype != "watermark":
            errors.append(f"{path}: capture.lookback_minutes is valid only for watermark archetype")

        for field in ("ordering_columns", "idempotency_columns"):
            undeclared = [name for name in capture.get(field, []) if name not in column_names]
            if undeclared:
                errors.append(f"{path}: capture.{field} columns are not declared: {', '.join(undeclared)}")

        if archetype == "watermark" and not source_timestamp and not capture.get("ordering_columns"):
            errors.append(
                f"{path}: watermark capture requires contract.source_timestamp or capture.ordering_columns"
            )

        if archetype == "full_change":
            if not capture.get("ordering_columns") and not changes.get("sequence_column"):
                errors.append(
                    f"{path}: full_change capture requires capture.ordering_columns or change_semantics.sequence_column"
                )
            if not capture.get("idempotency_columns"):
                errors.append(f"{path}: full_change capture requires capture.idempotency_columns")

        if archetype == "snapshot_diff" and changes.get("delete_semantics") != "inferred_snapshot_diff":
            errors.append(
                f"{path}: snapshot_diff capture requires change_semantics.delete_semantics=inferred_snapshot_diff"
            )

    return errors


def validate_dataset(
    document: dict[str, Any],
    path: Path,
    project_root: Path,
    raw_schema: dict[str, Any],
) -> list[str]:
    dataset = document["dataset"]
    errors: list[str] = []

    if dataset["load_strategy"] in _KEYED_STRATEGIES and not dataset.get("business_key"):
        errors.append(f"{path}: load_strategy {dataset['load_strategy']} requires dataset.business_key")

    freshness = dataset.get("freshness")
    if freshness and freshness["warn_after_minutes"] > freshness["error_after_minutes"]:
        errors.append(f"{path}: freshness warn_after_minutes must be <= error_after_minutes")

    contract_path = (project_root / dataset["raw_contract"]).resolve()
    try:
        contract_path.relative_to(project_root.resolve())
    except ValueError:
        errors.append(f"{path}: raw_contract escapes project root: {dataset['raw_contract']}")
        return errors

    if not contract_path.is_file():
        errors.append(f"{path}: raw_contract not found: {dataset['raw_contract']}")
        return errors

    contract_document = load_document(contract_path)
    contract_schema_errors = schema_errors(contract_document, raw_schema, contract_path)
    errors.extend(contract_schema_errors)
    if not contract_schema_errors:
        errors.extend(validate_raw_contract(contract_document, contract_path))

    return errors


def validate_project_tree(project_root: Path, schema_dir: Path) -> list[str]:
    project_root = project_root.resolve()
    schema_dir = schema_dir.resolve()
    errors: list[str] = []

    project_file = project_root / "config" / "project.yml"
    datasets_dir = project_root / "config" / "datasets"

    if not project_file.is_file():
        return [f"{project_file}: required project metadata file not found"]
    if not datasets_dir.is_dir():
        return [f"{datasets_dir}: required datasets directory not found"]

    project_schema = load_schema(schema_dir, "project")
    dataset_schema = load_schema(schema_dir, "dataset")
    raw_schema = load_schema(schema_dir, "raw_contract")

    project_document = load_document(project_file)
    errors.extend(schema_errors(project_document, project_schema, project_file))

    dataset_paths = sorted([*datasets_dir.glob("*.yml"), *datasets_dir.glob("*.yaml")])
    if not dataset_paths:
        errors.append(f"{datasets_dir}: at least one dataset metadata file is required")
        return errors

    seen_ids: dict[str, Path] = {}
    for dataset_path in dataset_paths:
        document = load_document(dataset_path)
        current_schema_errors = schema_errors(document, dataset_schema, dataset_path)
        errors.extend(current_schema_errors)
        if current_schema_errors:
            continue

        dataset_id = document["dataset"]["id"]
        if dataset_id in seen_ids:
            errors.append(
                f"{dataset_path}: duplicate dataset.id {dataset_id!r}; first declared in {seen_ids[dataset_id]}"
            )
        else:
            seen_ids[dataset_id] = dataset_path

        errors.extend(validate_dataset(document, dataset_path, project_root, raw_schema))

    return errors
