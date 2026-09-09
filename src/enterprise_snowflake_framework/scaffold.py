from __future__ import annotations

from pathlib import Path

import yaml

SUPPORTED_PATTERNS = {"append", "full_refresh", "scd1", "scd2"}
SCAFFOLD_FILES = ("README.md", "001_objects.sql", "010_apply.sql", "020_validate.sql")


def _repo_template_root() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _pipeline_yaml(pattern: str, dataset_id: str, raw_contract: str, contract: dict) -> str:
    entity = contract["entity"].upper()
    business_key = list(contract["business_key"])
    event_order = list(contract.get("ordering_columns", []))
    idempotency_key = list(contract.get("idempotency_key", []))
    source_timestamp = contract.get("source_timestamp")
    changes = contract["change_semantics"]
    operation_column = changes.get("operation_column")
    delete_values = list(changes.get("delete_values", []))

    excluded = set(business_key) | set(event_order) | {"ingested_at"}
    if operation_column:
        excluded.add(operation_column)
    tracked_columns = [
        column["name"] for column in contract["columns"] if column["name"] not in excluded
    ]

    lines = [
        "version: 1",
        "pipeline:",
        f"  id: {dataset_id}",
        f"  pattern: {pattern}",
        f"  raw_contract: {raw_contract}",
        "  input:",
        f"    relation: BRONZE.{entity}",
        "  output:",
    ]

    if pattern == "scd2":
        lines.extend([
            f"    history: SILVER_CANONICAL.{entity}_HISTORY",
            f"    current: SILVER_CANONICAL.{entity}_CURRENT",
        ])
    elif pattern == "scd1":
        lines.append(f"    current: SILVER_CANONICAL.{entity}")
    else:
        lines.append(f"    relation: SILVER_CANONICAL.{entity}")

    if pattern in {"scd1", "scd2"}:
        lines.append("  business_key:")
        lines.extend(f"    - {item}" for item in business_key)
        lines.append("  event_order:")
        lines.extend(f"    - {item}" for item in event_order)

    if pattern in {"append", "scd2"}:
        lines.append("  idempotency_key:")
        lines.extend(f"    - {item}" for item in idempotency_key)

    if pattern == "scd2":
        lines.append(f"  effective_at: {source_timestamp}")
        if not tracked_columns:
            raise ValueError("scd2 scaffold requires at least one tracked payload column")
        lines.append("  tracked_columns:")
        lines.extend(f"    - {item}" for item in tracked_columns)

    if pattern in {"scd1", "scd2"} and changes.get("delete_semantics") == "tombstone":
        lines.extend(["  delete:", f"    column: {operation_column}", "    values:"])
        lines.extend(f"      - {item}" for item in delete_values)

    return "\n".join(lines) + "\n"


def scaffold_pipeline(
    *,
    project_root: Path,
    pattern: str,
    dataset_id: str,
    raw_contract: str,
    force: bool = False,
    template_root: Path | None = None,
) -> Path:
    if pattern not in SUPPORTED_PATTERNS:
        raise ValueError(f"unsupported scaffold pattern: {pattern}")

    project_root = project_root.resolve()
    contract_path = (project_root / raw_contract).resolve()
    contract_path.relative_to(project_root)
    if not contract_path.is_file():
        raise FileNotFoundError(f"RAW contract not found: {raw_contract}")

    document = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("contract"), dict):
        raise ValueError(f"invalid RAW contract document: {raw_contract}")
    contract = document["contract"]

    destination = project_root / "silver_processing" / dataset_id
    if destination.exists() and any(destination.iterdir()) and not force:
        raise FileExistsError(f"Silver pipeline already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    root = (template_root or _repo_template_root()).resolve()
    pattern_root = root / pattern
    if not pattern_root.is_dir():
        raise FileNotFoundError(f"template directory not found: {pattern_root}")

    replacements = {
        "__DATASET_ID__": dataset_id,
        "__ENTITY_UPPER__": str(contract["entity"]).upper(),
        "__RAW_CONTRACT__": raw_contract,
    }

    (destination / "pipeline.yml").write_text(
        _pipeline_yaml(pattern, dataset_id, raw_contract, contract), encoding="utf-8"
    )

    for filename in SCAFFOLD_FILES:
        source = pattern_root / filename
        if not source.is_file():
            raise FileNotFoundError(f"template file not found: {source}")
        text = source.read_text(encoding="utf-8")
        for marker, value in replacements.items():
            text = text.replace(marker, value)
        (destination / filename).write_text(text, encoding="utf-8")

    return destination
