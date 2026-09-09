from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SOURCE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


@dataclass(frozen=True)
class AddSourceResult:
    source_id: str
    created: bool
    paths: tuple[Path, ...]
    reason: str | None = None


def source_manifest_path(project_root: Path, source_id: str) -> Path:
    return project_root.resolve() / "config" / "sources" / f"{source_id}.yml"


def source_paths(project_root: Path, source_id: str) -> tuple[Path, ...]:
    root = project_root.resolve()
    return (
        root / "config" / "sources" / f"{source_id}.yml",
        root / "contracts" / "raw" / source_id,
        root / "ingestion" / source_id,
        root / "silver_processing" / source_id,
    )


def _validate_source_id(source_id: str) -> None:
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise ValueError("source id must match ^[a-z][a-z0-9_]{1,63}$")


def _project_owner(project_root: Path) -> str:
    project_file = project_root / "config" / "project.yml"
    if not project_file.is_file():
        raise FileNotFoundError(f"project is not initialized: {project_file}")
    document = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    try:
        code = str(document["project"]["code"])
    except (TypeError, KeyError) as exc:
        raise ValueError(f"invalid project metadata: {project_file}") from exc
    return code.lower()


def add_source(project_root: Path, source_id: str) -> AddSourceResult:
    project_root = project_root.resolve()
    _validate_source_id(source_id)
    paths = source_paths(project_root, source_id)

    if any(path.exists() for path in paths):
        return AddSourceResult(source_id=source_id, created=False, paths=paths, reason="already exists")

    owner = _project_owner(project_root)
    manifest = (
        "schema_version: 1\n\n"
        "source:\n"
        f"  id: {source_id}\n"
        f"  owner: {owner}\n\n"
        "datasets: {}\n"
    )

    paths[1].mkdir(parents=True, exist_ok=False)
    paths[2].mkdir(parents=True, exist_ok=False)
    paths[3].mkdir(parents=True, exist_ok=False)
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    paths[0].write_text(manifest, encoding="utf-8")

    return AddSourceResult(source_id=source_id, created=True, paths=paths)


def load_source_manifest(project_root: Path, source_id: str) -> dict[str, Any]:
    _validate_source_id(source_id)
    path = source_manifest_path(project_root, source_id)
    if not path.is_file():
        raise FileNotFoundError(f"source manifest not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"source manifest root must be an object: {path}")
    source = document.get("source")
    datasets = document.get("datasets")
    if not isinstance(source, dict) or source.get("id") != source_id:
        raise ValueError(f"source manifest id must match filename: {path}")
    if not isinstance(datasets, dict):
        raise ValueError(f"source manifest datasets must be an object: {path}")
    return document
