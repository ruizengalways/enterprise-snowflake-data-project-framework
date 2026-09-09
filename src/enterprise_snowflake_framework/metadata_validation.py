from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .dataset_metadata import DatasetMetadataError, canonical_dataset, validate_runtime_model
from .scd2_validation import validate_scd2_metadata

SCHEMA_FILES = {
    "project": "project.schema.json",
    "dataset": "dataset.schema.json",
    "raw_contract": "raw_contract.schema.json",
}


class MetadataValidationError(ValueError):
    pass


def load_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise MetadataValidationError(f"{path}: document root must be an object")
    return value


def load_schema(schema_dir: Path, kind: str) -> dict[str, Any]:
    return json.loads((schema_dir / SCHEMA_FILES[kind]).read_text(encoding="utf-8"))


def schema_errors(document: dict[str, Any], schema: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    for error in sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda item: list(item.absolute_path),
    ):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{path}: {location}: {error.message}")
    return errors


def validate_raw_contract(document: dict[str, Any], path: Path) -> list[str]:
    """Validate source semantics only; connector implementation and checkpoints are out of scope."""
    contract = document["contract"]
    columns = contract["columns"]
    names = [column["name"] for column in columns]
    column_names = set(names)
    columns_by_name = {column["name"]: column for column in columns}
    errors: list[str] = []

    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"{path}: contract.columns contains duplicate names: {', '.join(duplicates)}")

    missing_keys = [name for name in contract["business_key"] if name not in column_names]
    if missing_keys:
        errors.append(f"{path}: business_key columns missing from columns: {', '.join(missing_keys)}")
    nullable_keys = [
        name for name in contract["business_key"]
        if name in columns_by_name and columns_by_name[name].get("nullable") is True
    ]
    if nullable_keys:
        errors.append(f"{path}: business_key columns must be nullable=false: {', '.join(nullable_keys)}")

    source_timestamp = contract.get("source_timestamp")
    if source_timestamp and source_timestamp not in column_names:
        errors.append(f"{path}: source_timestamp column is not declared: {source_timestamp}")

    for field in ("ordering_columns", "idempotency_key"):
        undeclared = [name for name in contract.get(field, []) if name not in column_names]
        if undeclared:
            errors.append(f"{path}: contract.{field} columns are not declared: {', '.join(undeclared)}")

    changes = contract["change_semantics"]
    if changes["mode"] == "cdc":
        for field in ("operation_column", "sequence_column"):
            column = changes.get(field)
            if not column:
                errors.append(f"{path}: CDC contract requires change_semantics.{field}")
            elif column not in column_names:
                errors.append(f"{path}: {field} column is not declared: {column}")
        sequence_column = changes.get("sequence_column")
        if sequence_column and sequence_column not in contract.get("ordering_columns", []):
            errors.append(f"{path}: CDC sequence_column must be present in contract.ordering_columns")

    if contract["capture_fidelity"] in {"full_change", "full_event"} and not contract.get("ordering_columns"):
        errors.append(f"{path}: full_change/full_event source fidelity requires contract.ordering_columns")

    return errors


def validate_dataset(
    document: dict[str, Any], path: Path, project_root: Path, raw_schema: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    try:
        dataset = canonical_dataset(document)
    except DatasetMetadataError as exc:
        return [f"{path}: {exc}"]

    errors.extend(validate_runtime_model(dataset, path))

    raw_contract_ref = dataset.get("raw_contract")
    if not raw_contract_ref:
        if dataset.get("load") and dataset["load"]["strategy"] in {
            "append_only", "incremental_merge", "scd1", "scd2"
        }:
            errors.append(
                f"{path}: source-maintenance strategy {dataset['load']['strategy']} requires dataset.raw_contract"
            )
        return errors

    contract_path = (project_root / raw_contract_ref).resolve()
    try:
        contract_path.relative_to(project_root.resolve())
    except ValueError:
        errors.append(f"{path}: raw_contract escapes project root: {raw_contract_ref}")
        return errors
    if not contract_path.is_file():
        errors.append(f"{path}: raw_contract not found: {raw_contract_ref}")
        return errors

    contract_document = load_document(contract_path)
    contract_schema_errors = schema_errors(contract_document, raw_schema, contract_path)
    errors.extend(contract_schema_errors)
    if contract_schema_errors:
        return errors

    raw_errors = validate_raw_contract(contract_document, contract_path)
    errors.extend(raw_errors)
    if raw_errors:
        return errors

    contract = contract_document["contract"]
    errors.extend(validate_scd2_metadata(dataset, contract, path))

    load = dataset.get("load")
    if load and load.get("business_key") and load["business_key"] != contract["business_key"]:
        errors.append(
            f"{path}: load.business_key must match raw contract business_key; "
            f"dataset={load['business_key']}, contract={contract['business_key']}"
        )
    if load and load.get("watermark_column"):
        declared = {column["name"] for column in contract["columns"]}
        if load["watermark_column"] not in declared:
            errors.append(
                f"{path}: load.watermark_column is not declared by raw contract: {load['watermark_column']}"
            )

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

    project_document = load_document(project_file)
    errors.extend(schema_errors(project_document, load_schema(schema_dir, "project"), project_file))
    dataset_schema = load_schema(schema_dir, "dataset")
    raw_schema = load_schema(schema_dir, "raw_contract")
    dataset_paths = sorted([*datasets_dir.glob("*.yml"), *datasets_dir.glob("*.yaml")])
    if not dataset_paths:
        return errors + [f"{datasets_dir}: at least one dataset metadata file is required"]

    seen_ids: dict[str, Path] = {}
    for dataset_path in dataset_paths:
        document = load_document(dataset_path)
        current_errors = schema_errors(document, dataset_schema, dataset_path)
        errors.extend(current_errors)
        if current_errors:
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
