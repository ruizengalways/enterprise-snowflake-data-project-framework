from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

import yaml

SUPPORTED_EXECUTION_MODELS = {"stream_task", "dynamic_table", "batch_sql", "custom"}
DYNAMIC_TABLE_PATTERNS = {"scd1", "full_refresh"}
BATCH_SQL_PATTERNS = {"full_refresh"}
STREAM_TRIGGER_PATTERNS = {"append", "scd1", "scd2"}

_UNQUOTED_IDENTIFIER_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class TaskExecution:
    warehouse: str
    minimum_trigger_interval_seconds: int | None = None
    timeout_seconds: int | None = None
    suspend_after_failures: int | None = None
    error_integration: str | None = None


@dataclass(frozen=True)
class VersionExecution:
    execution_model: str
    target_lag: str | None = None
    warehouse: str | None = None
    refresh_mode: str | None = None
    task: TaskExecution | None = None


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


def _validated_identifier(value: str, *, field: str) -> str:
    normalized = value.strip().upper()
    if not normalized or not _UNQUOTED_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{field} must be an unquoted Snowflake identifier")
    return normalized


def validate_task_execution(pattern: str, task: TaskExecution) -> TaskExecution:
    warehouse = _validated_identifier(task.warehouse, field="task warehouse")
    interval = task.minimum_trigger_interval_seconds
    if interval is not None:
        if pattern not in STREAM_TRIGGER_PATTERNS:
            raise ValueError(
                "task minimum trigger interval is only valid for stream-triggered "
                "append/scd1/scd2 implementations"
            )
        if interval < 10 or interval > 604800:
            raise ValueError("task minimum trigger interval must be between 10 and 604800 seconds")
    timeout = task.timeout_seconds
    if timeout is not None and (timeout < 0 or timeout > 604800):
        raise ValueError("task timeout must be between 0 and 604800 seconds")
    suspend_after = task.suspend_after_failures
    if suspend_after is not None and suspend_after < 0:
        raise ValueError("task suspend-after-failures must be zero or greater")
    error_integration = task.error_integration
    if error_integration is not None:
        error_integration = _validated_identifier(
            error_integration, field="task error integration"
        )
    return TaskExecution(
        warehouse=warehouse,
        minimum_trigger_interval_seconds=interval,
        timeout_seconds=timeout,
        suspend_after_failures=suspend_after,
        error_integration=error_integration,
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
    task_doc = version_doc.get("task", {}) if isinstance(version_doc.get("task"), dict) else {}
    task: TaskExecution | None = None
    if task_doc:
        if execution_model != "stream_task":
            raise ValueError("task configuration is only valid for execution_model=stream_task")
        if not task_doc.get("warehouse"):
            raise ValueError("task configuration requires warehouse")
        task = validate_task_execution(
            pattern,
            TaskExecution(
                warehouse=str(task_doc["warehouse"]),
                minimum_trigger_interval_seconds=task_doc.get("minimum_trigger_interval_seconds"),
                timeout_seconds=task_doc.get("timeout_seconds"),
                suspend_after_failures=task_doc.get("suspend_after_failures"),
                error_integration=task_doc.get("error_integration"),
            ),
        )
    return VersionExecution(
        execution_model=execution_model,
        target_lag=dynamic.get("target_lag"),
        warehouse=dynamic.get("warehouse"),
        refresh_mode=dynamic.get("refresh_mode"),
        task=task,
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
    elif execution.execution_model == "stream_task" and execution.task is not None:
        task = execution.task
        lines.extend(["  task:", f"    warehouse: {task.warehouse}"])
        if task.minimum_trigger_interval_seconds is not None:
            lines.append(
                "    minimum_trigger_interval_seconds: "
                f"{task.minimum_trigger_interval_seconds}"
            )
        if task.timeout_seconds is not None:
            lines.append(f"    timeout_seconds: {task.timeout_seconds}")
        if task.suspend_after_failures is not None:
            lines.append(f"    suspend_after_failures: {task.suspend_after_failures}")
        if task.error_integration is not None:
            lines.append(f"    error_integration: {task.error_integration}")
    return "\n".join(lines) + "\n"
