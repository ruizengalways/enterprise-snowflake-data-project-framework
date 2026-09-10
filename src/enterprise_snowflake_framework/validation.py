from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .execution_model import default_execution_model, validate_execution_model

SCHEMA_FILES = {
    "project": "project.schema.json",
    "raw_contract": "raw_contract.schema.json",
    "silver_pipeline": "silver_pipeline.schema.json",
    "source_manifest": "source_manifest.schema.json",
    "version": "version.schema.json",
}


class MetadataValidationError(ValueError):
    pass


def default_schema_dir() -> Path:
    return Path(__file__).resolve().parent / "schemas"


def load_document(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise MetadataValidationError(f"{path}: cannot parse document: {exc}") from exc
    if not isinstance(value, dict):
        raise MetadataValidationError(f"{path}: document root must be an object")
    return value


def load_schema(schema_dir: Path, kind: str) -> dict[str, Any]:
    return json.loads((schema_dir / SCHEMA_FILES[kind]).read_text(encoding="utf-8"))


def schema_errors(document: dict[str, Any], schema: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path)):
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
    nullable_keys = [
        name for name in contract["business_key"] if name in by_name and by_name[name].get("nullable") is True
    ]
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


def validate_source_manifest(
    document: dict[str, Any],
    path: Path,
    project_root: Path,
    raw_schema: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    source_id = document["source"]["id"]
    if path.stem != source_id:
        errors.append(f"{path}: source.id must match manifest filename: {path.stem}")

    for dataset_id, config in sorted(document["datasets"].items()):
        raw_contract = config["raw_contract"]
        expected_prefix = f"contracts/raw/{source_id}/"
        if not raw_contract.startswith(expected_prefix):
            errors.append(
                f"{path}: datasets.{dataset_id}.raw_contract must be under {expected_prefix}"
            )
            continue
        contract_path, path_errors = _resolve_project_path(project_root, raw_contract, path)
        errors.extend(path_errors)
        if contract_path is None:
            continue
        raw_document = load_document(contract_path)
        current = schema_errors(raw_document, raw_schema, contract_path)
        errors.extend(current)
        if current:
            continue
        errors.extend(validate_raw_contract(raw_document, contract_path))
        if raw_document["contract"]["source_system"] != source_id:
            errors.append(
                f"{contract_path}: contract.source_system must match source manifest id {source_id}"
            )
    return errors


def validate_silver_pipeline(
    document: dict[str, Any],
    path: Path,
    project_root: Path,
    raw_schema: dict[str, Any],
    source_manifests: dict[str, dict[str, Any]],
) -> list[str]:
    pipeline = document["pipeline"]
    errors: list[str] = []

    relative = path.relative_to(project_root / "silver_processing")
    if len(relative.parts) != 3:
        return [f"{path}: pipeline.yml must be under silver_processing/<source>/<dataset>/"]
    source_id, dataset_id, _ = relative.parts
    if pipeline["id"] != dataset_id:
        errors.append(f"{path}: pipeline.id must match dataset directory {dataset_id}")

    contract_path, path_errors = _resolve_project_path(project_root, pipeline["raw_contract"], path)
    errors.extend(path_errors)
    if contract_path is None:
        return errors

    expected_contract_root = (project_root / "contracts" / "raw" / source_id).resolve()
    try:
        contract_path.relative_to(expected_contract_root)
    except ValueError:
        errors.append(f"{path}: raw_contract must be under contracts/raw/{source_id}/")

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

    if contract["source_system"] != source_id:
        errors.append(f"{path}: RAW contract source_system must match pipeline source directory {source_id}")
    if not pipeline["input"]["relation"].startswith("BRONZE."):
        errors.append(f"{path}: Silver processing input must be a BRONZE relation")
    for name, relation in pipeline["output"].items():
        if not relation.startswith("SILVER."):
            errors.append(f"{path}: output.{name} must be a SILVER relation")

    undeclared = [name for name in pipeline.get("tracked_columns", []) if name not in declared]
    if undeclared:
        errors.append(
            f"{path}: pipeline.tracked_columns columns are not in the RAW contract: {', '.join(undeclared)}"
        )

    if pattern == "scd2":
        if contract["capture_fidelity"] not in {"full_change", "full_event"}:
            errors.append(
                f"{path}: scd2 requires full_change/full_event evidence; "
                f"RAW capture_fidelity={contract['capture_fidelity']}"
            )
        if not contract.get("source_timestamp"):
            errors.append(f"{path}: scd2 requires RAW contract source_timestamp")
        if not contract.get("ordering_columns"):
            errors.append(f"{path}: scd2 requires RAW contract ordering_columns")
        if not contract.get("idempotency_key"):
            errors.append(f"{path}: scd2 requires RAW contract idempotency_key")

    manifest = source_manifests.get(source_id)
    if manifest is None:
        errors.append(f"{path}: source manifest not found for pipeline source {source_id}")
    else:
        dataset_config = manifest["datasets"].get(dataset_id)
        if not isinstance(dataset_config, dict):
            errors.append(f"{path}: dataset is not declared in config/sources/{source_id}.yml")
        else:
            if dataset_config["pattern"] != pattern:
                errors.append(f"{path}: pipeline.pattern must match source manifest pattern")
            if dataset_config["raw_contract"] != pipeline["raw_contract"]:
                errors.append(f"{path}: pipeline.raw_contract must match source manifest raw_contract")
    return errors


def validate_version_document(
    document: dict[str, Any], path: Path, project_root: Path,
    source_manifests: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    relative = path.relative_to(project_root / "silver_processing")
    parts = relative.parts
    if len(parts) == 3 and parts[2] == "version.yml":
        source_id, dataset_id = parts[0], parts[1]
        expected_version = "v1"
    elif len(parts) == 5 and parts[2] == "versions" and parts[4] == "version.yml":
        source_id, dataset_id, expected_version = parts[0], parts[1], parts[3]
    else:
        return [f"{path}: version.yml must be under a dataset root or versions/vN directory"]
    version = document["version"]
    if version["dataset"] != f"{source_id}.{dataset_id}":
        errors.append(f"{path}: version.dataset must match {source_id}.{dataset_id}")
    if version["id"] != expected_version:
        errors.append(f"{path}: version.id must match implementation directory {expected_version}")
    manifest = source_manifests.get(source_id)
    config = manifest.get("datasets", {}).get(dataset_id) if isinstance(manifest, dict) else None
    if not isinstance(config, dict) or not isinstance(config.get("pattern"), str):
        errors.append(f"{path}: logical dataset declaration not found for execution-model validation")
        return errors
    pattern = str(config["pattern"])
    execution_model = str(version.get("execution_model") or default_execution_model(pattern))
    try:
        validate_execution_model(pattern, execution_model)
    except ValueError as exc:
        errors.append(f"{path}: {exc}")
    return errors


def validate_project_tree(project_root: Path, schema_dir: Path | None = None) -> list[str]:
    project_root = project_root.resolve()
    schema_dir = (schema_dir or default_schema_dir()).resolve()
    errors: list[str] = []
    project_file = project_root / "config" / "project.yml"
    if not project_file.is_file():
        return [f"{project_file}: required project metadata file not found"]

    try:
        project_document = load_document(project_file)
        errors.extend(schema_errors(project_document, load_schema(schema_dir, "project"), project_file))

        raw_schema = load_schema(schema_dir, "raw_contract")
        raw_root = project_root / "contracts" / "raw"
        raw_paths = (
            sorted([*raw_root.rglob("*.yml"), *raw_root.rglob("*.yaml")]) if raw_root.is_dir() else []
        )
        for raw_path in raw_paths:
            document = load_document(raw_path)
            current = schema_errors(document, raw_schema, raw_path)
            errors.extend(current)
            if current:
                continue
            errors.extend(validate_raw_contract(document, raw_path))
            relative = raw_path.relative_to(raw_root)
            if len(relative.parts) < 2:
                errors.append(f"{raw_path}: RAW contracts must be grouped under contracts/raw/<source>/")
            elif document["contract"]["source_system"] != relative.parts[0]:
                errors.append(
                    f"{raw_path}: contract.source_system must match RAW source directory {relative.parts[0]}"
                )

        source_schema = load_schema(schema_dir, "source_manifest")
        source_manifests: dict[str, dict[str, Any]] = {}
        source_root = project_root / "config" / "sources"
        source_paths = (
            sorted([*source_root.glob("*.yml"), *source_root.glob("*.yaml")]) if source_root.is_dir() else []
        )
        for source_path in source_paths:
            document = load_document(source_path)
            current = schema_errors(document, source_schema, source_path)
            errors.extend(current)
            if current:
                continue
            source_id = document["source"]["id"]
            source_manifests[source_id] = document
            errors.extend(validate_source_manifest(document, source_path, project_root, raw_schema))

        silver_schema = load_schema(schema_dir, "silver_pipeline")
        version_schema = load_schema(schema_dir, "version")
        silver_root = project_root / "silver_processing"
        pipeline_paths = sorted(silver_root.rglob("pipeline.yml")) if silver_root.is_dir() else []
        for pipeline_path in pipeline_paths:
            document = load_document(pipeline_path)
            current = schema_errors(document, silver_schema, pipeline_path)
            errors.extend(current)
            if not current:
                errors.extend(
                    validate_silver_pipeline(
                        document, pipeline_path, project_root, raw_schema, source_manifests
                    )
                )
        version_paths = sorted(silver_root.rglob("version.yml")) if silver_root.is_dir() else []
        for version_path in version_paths:
            document = load_document(version_path)
            current = schema_errors(document, version_schema, version_path)
            errors.extend(current)
            if not current:
                errors.extend(validate_version_document(document, version_path, project_root, source_manifests))
    except MetadataValidationError as exc:
        errors.append(str(exc))
    return errors
