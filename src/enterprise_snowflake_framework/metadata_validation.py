from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

SCHEMA_FILES = {
    "project": "project.schema.json",
    "raw_contract": "raw_contract.schema.json",
    "silver_pipeline": "silver_pipeline.schema.json",
}


class MetadataValidationError(ValueError):
    pass


def default_schema_dir() -> Path:
    return Path(__file__).resolve().parent / "schemas"


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
    for error in sorted(Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{path}: {location}: {error.message}")
    return errors


def validate_raw_contract(document: dict[str, Any], path: Path) -> list[str]:
    contract = document["contract"]
    columns = contract["columns"]
    names = [column["name"] for column in columns]
    declared = set(names)
    by_name = {column["name"]: column for column in columns}
    errors: list[str] = []

    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"{path}: contract.columns contains duplicate names: {', '.join(duplicates)}")
    missing_keys = [name for name in contract["business_key"] if name not in declared]
    if missing_keys:
        errors.append(f"{path}: business_key columns missing from columns: {', '.join(missing_keys)}")
    nullable_keys = [name for name in contract["business_key"] if name in by_name and by_name[name].get("nullable") is True]
    if nullable_keys:
        errors.append(f"{path}: business_key columns must be nullable=false: {', '.join(nullable_keys)}")

    source_timestamp = contract.get("source_timestamp")
    if source_timestamp and source_timestamp not in declared:
        errors.append(f"{path}: source_timestamp column is not declared: {source_timestamp}")
    for field in ("ordering_columns", "idempotency_key"):
        undeclared = [name for name in contract.get(field, []) if name not in declared]
        if undeclared:
            errors.append(f"{path}: contract.{field} columns are not declared: {', '.join(undeclared)}")

    changes = contract["change_semantics"]
    if changes["mode"] == "cdc":
        for field in ("operation_column", "sequence_column"):
            column = changes.get(field)
            if not column:
                errors.append(f"{path}: CDC contract requires change_semantics.{field}")
            elif column not in declared:
                errors.append(f"{path}: {field} column is not declared: {column}")
        sequence = changes.get("sequence_column")
        if sequence and sequence not in contract.get("ordering_columns", []):
            errors.append(f"{path}: CDC sequence_column must be present in contract.ordering_columns")

    if contract["capture_fidelity"] in {"full_change", "full_event"} and not contract.get("ordering_columns"):
        errors.append(f"{path}: full_change/full_event source fidelity requires contract.ordering_columns")
    return errors


def _resolve_project_path(project_root: Path, relative_path: str, owner_path: Path) -> tuple[Path | None, list[str]]:
    resolved = (project_root / relative_path).resolve()
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError:
        return None, [f"{owner_path}: path escapes project root: {relative_path}"]
    if not resolved.is_file():
        return None, [f"{owner_path}: referenced file not found: {relative_path}"]
    return resolved, []


def validate_silver_pipeline(document: dict[str, Any], path: Path, project_root: Path, raw_schema: dict[str, Any]) -> list[str]:
    pipeline = document["pipeline"]
    errors: list[str] = []
    contract_path, path_errors = _resolve_project_path(project_root, pipeline["raw_contract"], path)
    errors.extend(path_errors)
    if contract_path is None:
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
    declared = {column["name"] for column in contract["columns"]}
    pattern = pipeline["pattern"]

    if not pipeline["input"]["relation"].startswith("BRONZE."):
        errors.append(f"{path}: Silver processing input must be a BRONZE relation")
    for name, relation in pipeline["output"].items():
        if not relation.startswith("SILVER"):
            errors.append(f"{path}: output.{name} must be a SILVER relation")

    for field in ("business_key", "event_order", "idempotency_key", "tracked_columns"):
        undeclared = [name for name in pipeline.get(field, []) if name not in declared]
        if undeclared:
            errors.append(f"{path}: pipeline.{field} columns are not in the RAW contract: {', '.join(undeclared)}")
    effective_at = pipeline.get("effective_at")
    if effective_at and effective_at not in declared:
        errors.append(f"{path}: pipeline.effective_at is not in the RAW contract: {effective_at}")
    delete = pipeline.get("delete")
    if delete and delete["column"] not in declared:
        errors.append(f"{path}: pipeline.delete.column is not in the RAW contract: {delete['column']}")

    if pattern in {"scd1", "scd2"} and pipeline.get("business_key") != contract["business_key"]:
        errors.append(f"{path}: pipeline.business_key must exactly match RAW contract business_key; pipeline={pipeline.get('business_key')}, contract={contract['business_key']}")
    if pattern in {"scd1", "scd2"} and pipeline.get("event_order") != contract.get("ordering_columns"):
        errors.append(f"{path}: pipeline.event_order must exactly match RAW contract ordering_columns; pipeline={pipeline.get('event_order')}, contract={contract.get('ordering_columns')}")
    if pattern in {"append", "scd2"} and pipeline.get("idempotency_key") != contract.get("idempotency_key"):
        errors.append(f"{path}: pipeline.idempotency_key must exactly match RAW contract idempotency_key")

    if pattern == "scd2":
        if contract["capture_fidelity"] not in {"full_change", "full_event"}:
            errors.append(f"{path}: scd2 requires full_change/full_event evidence; RAW capture_fidelity={contract['capture_fidelity']}")
        if effective_at != contract.get("source_timestamp"):
            errors.append(f"{path}: scd2 effective_at must match RAW contract source_timestamp")

    changes = contract["change_semantics"]
    if changes.get("delete_semantics") == "tombstone" and pattern in {"scd1", "scd2"}:
        if not delete:
            errors.append(f"{path}: tombstone RAW contract requires pipeline.delete")
        else:
            if delete["column"] != changes.get("operation_column"):
                errors.append(f"{path}: pipeline.delete.column must match RAW operation_column")
            if set(delete["values"]) != set(changes.get("delete_values", [])):
                errors.append(f"{path}: pipeline.delete.values must match RAW delete_values")

    for required in ("README.md", "001_objects.sql", "010_apply.sql", "020_validate.sql"):
        if not (path.parent / required).is_file():
            errors.append(f"{path.parent}: required readable Silver pipeline file missing: {required}")
    return errors


def validate_project_tree(project_root: Path, schema_dir: Path | None = None) -> list[str]:
    project_root = project_root.resolve()
    schema_dir = (schema_dir or default_schema_dir()).resolve()
    errors: list[str] = []
    project_file = project_root / "config" / "project.yml"
    if not project_file.is_file():
        return [f"{project_file}: required project metadata file not found"]

    project_document = load_document(project_file)
    errors.extend(schema_errors(project_document, load_schema(schema_dir, "project"), project_file))

    raw_schema = load_schema(schema_dir, "raw_contract")
    raw_dir = project_root / "contracts" / "raw"
    raw_paths = sorted([*raw_dir.glob("*.yml"), *raw_dir.glob("*.yaml")]) if raw_dir.is_dir() else []
    if not raw_paths:
        errors.append(f"{raw_dir}: at least one RAW contract is required")
    for raw_path in raw_paths:
        document = load_document(raw_path)
        current = schema_errors(document, raw_schema, raw_path)
        errors.extend(current)
        if not current:
            errors.extend(validate_raw_contract(document, raw_path))

    silver_schema = load_schema(schema_dir, "silver_pipeline")
    silver_root = project_root / "silver_processing"
    pipeline_paths = sorted(silver_root.glob("*/pipeline.yml")) if silver_root.is_dir() else []
    for pipeline_path in pipeline_paths:
        document = load_document(pipeline_path)
        current = schema_errors(document, silver_schema, pipeline_path)
        errors.extend(current)
        if not current:
            errors.extend(validate_silver_pipeline(document, pipeline_path, project_root, raw_schema))
    return errors
