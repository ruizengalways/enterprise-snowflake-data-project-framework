from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_EXECUTION_MODELS = {"stream_task", "dynamic_table", "batch_sql", "custom"}
DYNAMIC_TABLE_PATTERNS = {"scd1", "full_refresh"}
BATCH_SQL_PATTERNS = {"full_refresh"}


@dataclass(frozen=True)
class VersionExecution:
    execution_model: str
    target_lag: str | None = None
    warehouse: str | None = None
    refresh_mode: str | None = None


def default_execution_model(pattern: str) -> str:
    return "custom" if pattern == "custom" else "stream_task"


def validate_execution_model(pattern: str, execution_model: str) -> None:
    if execution_model not in SUPPORTED_EXECUTION_MODELS:
        raise ValueError(
            "execution_model must be one of: " + ", ".join(sorted(SUPPORTED_EXECUTION_MODELS))
        )
    if pattern == "custom":
        if execution_model != "custom":
            raise ValueError("custom semantic pattern requires execution_model=custom")
        return
    if execution_model == "custom":
        raise ValueError("execution_model=custom is reserved for pattern=custom")
    if execution_model == "dynamic_table" and pattern not in DYNAMIC_TABLE_PATTERNS:
        raise ValueError(
            f"pattern={pattern} does not support execution_model=dynamic_table yet; "
            "supported patterns are scd1 and full_refresh"
        )
    if execution_model == "batch_sql" and pattern not in BATCH_SQL_PATTERNS:
        raise ValueError(
            f"pattern={pattern} does not support execution_model=batch_sql yet; "
            "the first implementation supports full_refresh only"
        )


def version_file(project_root: Path, source_id: str, dataset_id: str, version: str) -> Path:
    root = project_root.resolve() / "silver_processing" / source_id / dataset_id
    return root / "version.yml" if version == "v1" else root / "versions" / version / "version.yml"


def load_version_execution(
    project_root: Path, source_id: str, dataset_id: str, version: str, *, pattern: str
) -> VersionExecution:
    path = version_file(project_root, source_id, dataset_id, version)
    if not path.is_file():
        # Pre-0.19 generated versions implicitly used the old pattern-coupled Stream/Task model.
        return VersionExecution(default_execution_model(pattern))
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    version_doc = document.get("version", {}) if isinstance(document, dict) else {}
    execution_model = str(version_doc.get("execution_model") or default_execution_model(pattern))
    validate_execution_model(pattern, execution_model)
    dynamic = version_doc.get("dynamic_table", {}) if isinstance(version_doc.get("dynamic_table"), dict) else {}
    return VersionExecution(
        execution_model=execution_model,
        target_lag=dynamic.get("target_lag"),
        warehouse=dynamic.get("warehouse"),
        refresh_mode=dynamic.get("refresh_mode"),
    )


def render_version_yaml(
    *, dataset_key: str, version: str, candidate: bool, execution: VersionExecution
) -> str:
    initial = "development" if candidate else "active"
    lines = [
        "schema_version: 1",
        "",
        "version:",
        f"  dataset: {dataset_key}",
        f"  id: {version}",
        f"  initial_status: {initial}",
        "  activation: explicit",
        f"  execution_model: {execution.execution_model}",
    ]
    if execution.execution_model == "dynamic_table":
        lines.extend(
            [
                "  dynamic_table:",
                f"    target_lag: {execution.target_lag or '5 minutes'}",
                f"    warehouse: {execution.warehouse}",
                f"    refresh_mode: {(execution.refresh_mode or 'incremental').lower()}",
            ]
        )
    return "\n".join(lines) + "\n"
