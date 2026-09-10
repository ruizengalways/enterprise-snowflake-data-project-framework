from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .source_management import load_source_manifest

STREAM_TASK_FILES = (
    "README.md",
    "pipeline.yml",
    "version.yml",
    "001_objects.sql",
    "010_apply.sql",
    "015_replay.sql",
    "020_validate.sql",
    "025_compare.sql",
    "030_task.sql",
    "040_register.sql",
    "050_publish.sql",
    "060_policy.sql",
    "deploy_manifest.fragment.txt",
)
DYNAMIC_TABLE_FILES = (
    "README.md",
    "pipeline.yml",
    "version.yml",
    "001_dynamic_table.sql",
    "020_validate.sql",
    "025_compare.sql",
    "040_register.sql",
    "050_publish.sql",
    "060_policy.sql",
    "deploy_manifest.fragment.txt",
)
BATCH_SQL_FILES = tuple(name for name in STREAM_TASK_FILES if name != "030_task.sql")
CUSTOM_FILES = (
    "README.md",
    "pipeline.yml",
    "version.yml",
    "001_objects.sql",
    "025_compare.sql",
    "040_register.sql",
    "050_publish.sql",
    "060_policy.sql",
    "deploy_manifest.fragment.txt",
)
# Backward-compatible public constant for pre-execution-model callers/tests.
STANDARD_DATASET_FILES = STREAM_TASK_FILES


def standard_dataset_files(destination: Path) -> tuple[str, ...]:
    version_file = destination / "version.yml"
    execution_model = "stream_task"
    if version_file.is_file():
        try:
            document = yaml.safe_load(version_file.read_text(encoding="utf-8"))
            version = document.get("version", {}) if isinstance(document, dict) else {}
            execution_model = str(version.get("execution_model") or "stream_task")
        except (OSError, yaml.YAMLError):
            execution_model = "stream_task"
    if execution_model == "dynamic_table":
        return DYNAMIC_TABLE_FILES
    if execution_model == "batch_sql":
        return BATCH_SQL_FILES
    if execution_model == "custom":
        return CUSTOM_FILES
    return STREAM_TASK_FILES


@dataclass(frozen=True)
class PlannedDataset:
    dataset_id: str
    pattern: str
    directory: Path
    missing_standard_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourcePlan:
    source_id: str
    manifest_count: int
    existing: tuple[PlannedDataset, ...]
    new: tuple[PlannedDataset, ...]

    @property
    def overwrite_count(self) -> int:
        return 0


def build_source_plan(project_root: Path, source_id: str) -> SourcePlan:
    project_root = project_root.resolve()
    manifest = load_source_manifest(project_root, source_id)
    datasets = manifest["datasets"]
    existing: list[PlannedDataset] = []
    new: list[PlannedDataset] = []

    for dataset_id, config in sorted(datasets.items()):
        if not isinstance(config, dict) or not isinstance(config.get("pattern"), str):
            raise ValueError(f"invalid dataset entry in source manifest: {source_id}.{dataset_id}")
        destination = project_root / "silver_processing" / source_id / dataset_id
        item = PlannedDataset(dataset_id=dataset_id, pattern=config["pattern"], directory=destination)
        if destination.exists():
            missing = tuple(name for name in standard_dataset_files(destination) if not (destination / name).is_file())
            existing.append(
                PlannedDataset(
                    dataset_id=dataset_id,
                    pattern=config["pattern"],
                    directory=destination,
                    missing_standard_files=missing,
                )
            )
        else:
            new.append(item)

    return SourcePlan(
        source_id=source_id,
        manifest_count=len(datasets),
        existing=tuple(existing),
        new=tuple(new),
    )
