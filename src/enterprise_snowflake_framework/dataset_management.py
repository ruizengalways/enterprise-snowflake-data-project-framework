from __future__ import annotations

import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path, PurePosixPath

import yaml as pyyaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .source_management import SOURCE_ID_PATTERN, source_manifest_path

DATASET_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
SUPPORTED_DATASET_PATTERNS = {"append", "full_refresh", "scd1", "scd2", "custom"}


@dataclass(frozen=True)
class AddDatasetResult:
    source_id: str
    dataset_id: str
    pattern: str
    raw_contract: str
    manifest: Path
    created: bool
    reason: str | None = None


def default_raw_contract(source_id: str, dataset_id: str) -> str:
    return f"contracts/raw/{source_id}/{dataset_id}.yml"


def _validate_source_id(source_id: str) -> None:
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise ValueError("source id must match ^[a-z][a-z0-9_]{1,63}$")


def _validate_dataset_id(dataset_id: str) -> None:
    if not DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise ValueError("dataset id must match ^[a-z][a-z0-9_]{1,63}$")


def _validate_pattern(pattern: str) -> None:
    if pattern not in SUPPORTED_DATASET_PATTERNS:
        raise ValueError(
            "pattern must be one of: " + ", ".join(sorted(SUPPORTED_DATASET_PATTERNS))
        )


def _validate_raw_contract(
    project_root: Path,
    source_id: str,
    raw_contract: str,
) -> None:
    relative = PurePosixPath(raw_contract)
    expected_prefix = PurePosixPath("contracts") / "raw" / source_id
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("raw contract must be a project-relative path")
    if relative.suffix not in {".yml", ".yaml"}:
        raise ValueError("raw contract must be a .yml or .yaml file")
    try:
        relative.relative_to(expected_prefix)
    except ValueError as exc:
        raise ValueError(
            f"raw contract for {source_id} must be under contracts/raw/{source_id}/"
        ) from exc

    path = (project_root / Path(*relative.parts)).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("raw contract path escapes project root") from exc
    if not path.is_file():
        raise FileNotFoundError(f"RAW contract not found: {raw_contract}")

    document = pyyaml.safe_load(path.read_text(encoding="utf-8"))
    contract = document.get("contract") if isinstance(document, dict) else None
    if not isinstance(contract, dict):
        raise ValueError(f"invalid RAW contract document: {raw_contract}")
    if contract.get("source_system") != source_id:
        raise ValueError(
            f"RAW contract source_system must match source {source_id}: "
            f"{contract.get('source_system')}"
        )


def add_dataset(
    project_root: Path,
    source_id: str,
    dataset_id: str,
    pattern: str,
    raw_contract: str | None = None,
) -> AddDatasetResult:
    project_root = project_root.resolve()
    _validate_source_id(source_id)
    _validate_dataset_id(dataset_id)
    _validate_pattern(pattern)

    manifest_path = source_manifest_path(project_root, source_id)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"source manifest not found: {manifest_path}")

    round_trip = YAML(typ="rt")
    round_trip.preserve_quotes = True
    round_trip.width = 4096
    document = round_trip.load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(document, CommentedMap):
        raise ValueError(f"source manifest root must be an object: {manifest_path}")

    source = document.get("source")
    datasets = document.get("datasets")
    if not isinstance(source, dict) or source.get("id") != source_id:
        raise ValueError(f"source manifest id must match filename: {manifest_path}")
    if not isinstance(datasets, dict):
        raise ValueError(f"source manifest datasets must be an object: {manifest_path}")

    resolved_raw_contract = raw_contract or default_raw_contract(source_id, dataset_id)
    if dataset_id in datasets:
        return AddDatasetResult(
            source_id=source_id,
            dataset_id=dataset_id,
            pattern=pattern,
            raw_contract=resolved_raw_contract,
            manifest=manifest_path,
            created=False,
            reason="already exists",
        )

    _validate_raw_contract(project_root, source_id, resolved_raw_contract)
    datasets[dataset_id] = CommentedMap(
        [
            ("pattern", pattern),
            ("raw_contract", resolved_raw_contract),
        ]
    )

    buffer = StringIO()
    round_trip.dump(document, buffer)
    manifest_path.write_text(buffer.getvalue(), encoding="utf-8")

    return AddDatasetResult(
        source_id=source_id,
        dataset_id=dataset_id,
        pattern=pattern,
        raw_contract=resolved_raw_contract,
        manifest=manifest_path,
        created=True,
    )
