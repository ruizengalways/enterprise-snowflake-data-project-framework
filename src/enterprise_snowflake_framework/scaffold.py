from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .plan import STANDARD_DATASET_FILES, SourcePlan, build_source_plan
from .source_management import load_source_manifest

SUPPORTED_PATTERNS = {"append", "full_refresh", "scd1", "scd2", "custom"}
SCAFFOLD_FILES = ("README.md", "001_objects.sql", "010_apply.sql", "020_validate.sql")


@dataclass(frozen=True)
class ScaffoldDatasetResult:
    source_id: str
    dataset_id: str
    pattern: str
    destination: Path
    created: bool
    missing_standard_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScaffoldAllResult:
    source_id: str
    created: tuple[ScaffoldDatasetResult, ...]
    skipped: tuple[ScaffoldDatasetResult, ...]

    @property
    def overwritten(self) -> int:
        return 0


def _repo_template_root() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _load_raw_contract(project_root: Path, raw_contract: str, source_id: str) -> dict[str, Any]:
    contract_path = (project_root / raw_contract).resolve()
    try:
        contract_path.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"RAW contract path escapes project root: {raw_contract}") from exc
    expected_root = (project_root / "contracts" / "raw" / source_id).resolve()
    try:
        contract_path.relative_to(expected_root)
    except ValueError as exc:
        raise ValueError(f"RAW contract for {source_id} must be under contracts/raw/{source_id}/") from exc
    if not contract_path.is_file():
        raise FileNotFoundError(f"RAW contract not found: {raw_contract}")
    document = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("contract"), dict):
        raise ValueError(f"invalid RAW contract document: {raw_contract}")
    contract = document["contract"]
    if contract.get("source_system") != source_id:
        raise ValueError(
            f"RAW contract source_system must match source {source_id}: {contract.get('source_system')}"
        )
    return contract


def _tracked_columns(contract: dict[str, Any]) -> list[str]:
    changes = contract.get("change_semantics", {})
    excluded = set(contract.get("business_key", []))
    excluded.update(contract.get("ordering_columns", []))
    excluded.update(contract.get("idempotency_key", []))
    excluded.add("ingested_at")
    if contract.get("source_timestamp"):
        excluded.add(contract["source_timestamp"])
    if changes.get("operation_column"):
        excluded.add(changes["operation_column"])
    if changes.get("sequence_column"):
        excluded.add(changes["sequence_column"])
    return [
        column["name"]
        for column in contract.get("columns", [])
        if isinstance(column, dict) and column.get("name") not in excluded
    ]


def _pipeline_yaml(pattern: str, dataset_id: str, raw_contract: str, contract: dict[str, Any]) -> str:
    entity = str(contract["entity"]).upper()
    lines = [
        "schema_version: 1",
        "",
        "pipeline:",
        f"  id: {dataset_id}",
        f"  pattern: {pattern}",
        f"  raw_contract: {raw_contract}",
        "",
        "  input:",
        f"    relation: BRONZE.{entity}",
        "",
        "  output:",
    ]
    if pattern == "scd2":
        lines.extend(
            [
                f"    history: SILVER.{entity}_HISTORY",
                f"    current: SILVER.{entity}_CURRENT",
            ]
        )
        tracked = _tracked_columns(contract)
        if not tracked:
            raise ValueError("scd2 scaffold requires at least one tracked payload column")
        lines.extend(["", "  tracked_columns:"])
        lines.extend(f"    - {item}" for item in tracked)
    elif pattern == "scd1":
        lines.append(f"    current: SILVER.{entity}")
    else:
        lines.append(f"    relation: SILVER.{entity}")
    return "\n".join(lines) + "\n"


def _prepare_dataset(
    *,
    project_root: Path,
    source_id: str,
    pattern: str,
    dataset_id: str,
    raw_contract: str,
    template_root: Path | None = None,
) -> tuple[Path, dict[str, str]]:
    if pattern not in SUPPORTED_PATTERNS:
        raise ValueError(f"unsupported scaffold pattern: {pattern}")
    project_root = project_root.resolve()
    destination = project_root / "silver_processing" / source_id / dataset_id
    if destination.exists():
        raise FileExistsError(f"domain-owned dataset directory already exists: {destination}")

    contract = _load_raw_contract(project_root, raw_contract, source_id)
    root = (template_root or _repo_template_root()).resolve()
    pattern_root = root / pattern
    if not pattern_root.is_dir():
        raise FileNotFoundError(f"template directory not found: {pattern_root}")

    replacements = {
        "__DATASET_ID__": dataset_id,
        "__ENTITY_UPPER__": str(contract["entity"]).upper(),
        "__RAW_CONTRACT__": raw_contract,
        "__SOURCE_ID__": source_id,
    }
    rendered: dict[str, str] = {
        "pipeline.yml": _pipeline_yaml(pattern, dataset_id, raw_contract, contract),
    }
    for filename in SCAFFOLD_FILES:
        source = pattern_root / filename
        if not source.is_file():
            raise FileNotFoundError(f"template file not found: {source}")
        text = source.read_text(encoding="utf-8")
        for marker, value in replacements.items():
            text = text.replace(marker, value)
        rendered[filename] = text
    return destination, rendered


def _write_prepared(destination: Path, rendered: dict[str, str]) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for filename, text in rendered.items():
        (destination / filename).write_text(text, encoding="utf-8")


def scaffold_pipeline(
    *,
    project_root: Path,
    source_id: str,
    pattern: str,
    dataset_id: str,
    template_root: Path | None = None,
) -> ScaffoldDatasetResult:
    project_root = project_root.resolve()
    manifest = load_source_manifest(project_root, source_id)
    config = manifest["datasets"].get(dataset_id)
    if not isinstance(config, dict):
        raise KeyError(f"dataset is not declared in source manifest: {source_id}.{dataset_id}")
    manifest_pattern = config.get("pattern")
    if pattern != manifest_pattern:
        raise ValueError(
            f"scaffold pattern must match source manifest for {source_id}.{dataset_id}: "
            f"requested={pattern}, manifest={manifest_pattern}"
        )
    raw_contract = config.get("raw_contract")
    if not isinstance(raw_contract, str):
        raise ValueError(f"raw_contract is required for {source_id}.{dataset_id}")

    destination = project_root / "silver_processing" / source_id / dataset_id
    if destination.exists():
        missing = tuple(name for name in STANDARD_DATASET_FILES if not (destination / name).is_file())
        return ScaffoldDatasetResult(
            source_id=source_id,
            dataset_id=dataset_id,
            pattern=pattern,
            destination=destination,
            created=False,
            missing_standard_files=missing,
        )

    destination, rendered = _prepare_dataset(
        project_root=project_root,
        source_id=source_id,
        pattern=pattern,
        dataset_id=dataset_id,
        raw_contract=raw_contract,
        template_root=template_root,
    )
    _write_prepared(destination, rendered)
    return ScaffoldDatasetResult(
        source_id=source_id,
        dataset_id=dataset_id,
        pattern=pattern,
        destination=destination,
        created=True,
    )


def scaffold_all(
    *, project_root: Path, source_id: str, template_root: Path | None = None
) -> ScaffoldAllResult:
    project_root = project_root.resolve()
    plan: SourcePlan = build_source_plan(project_root, source_id)
    manifest = load_source_manifest(project_root, source_id)

    prepared: list[tuple[str, str, Path, dict[str, str]]] = []
    for item in plan.new:
        config = manifest["datasets"][item.dataset_id]
        raw_contract = config.get("raw_contract")
        if not isinstance(raw_contract, str):
            raise ValueError(f"raw_contract is required for {source_id}.{item.dataset_id}")
        destination, rendered = _prepare_dataset(
            project_root=project_root,
            source_id=source_id,
            pattern=item.pattern,
            dataset_id=item.dataset_id,
            raw_contract=raw_contract,
            template_root=template_root,
        )
        prepared.append((item.dataset_id, item.pattern, destination, rendered))

    created: list[ScaffoldDatasetResult] = []
    for dataset_id, pattern, destination, rendered in prepared:
        _write_prepared(destination, rendered)
        created.append(
            ScaffoldDatasetResult(
                source_id=source_id,
                dataset_id=dataset_id,
                pattern=pattern,
                destination=destination,
                created=True,
            )
        )

    skipped = tuple(
        ScaffoldDatasetResult(
            source_id=source_id,
            dataset_id=item.dataset_id,
            pattern=item.pattern,
            destination=item.directory,
            created=False,
            missing_standard_files=item.missing_standard_files,
        )
        for item in plan.existing
    )
    return ScaffoldAllResult(source_id=source_id, created=tuple(created), skipped=skipped)
