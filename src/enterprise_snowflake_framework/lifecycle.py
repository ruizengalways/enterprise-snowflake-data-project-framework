from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .execution_model import load_version_execution
from .pipeline_sql import build_names
from .scaffold import _load_raw_contract
from .source_management import load_source_manifest
from .versioning import existing_versions, validate_version

LIFECYCLE_ACTIONS = {"pause", "resume", "decommission"}
_OPERATION_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


@dataclass(frozen=True)
class LifecycleScriptsResult:
    source_id: str
    dataset_id: str
    action: str
    operation_id: str
    destination: Path
    created: bool


def _context(project_root: Path, source_id: str, dataset_id: str) -> tuple[str, str, dict]:
    manifest = load_source_manifest(project_root, source_id)
    config = manifest["datasets"].get(dataset_id)
    if not isinstance(config, dict):
        raise KeyError(f"dataset is not declared in source manifest: {source_id}.{dataset_id}")
    pattern = config.get("pattern")
    raw_contract = config.get("raw_contract")
    if not isinstance(pattern, str) or not isinstance(raw_contract, str):
        raise ValueError(f"invalid source manifest dataset entry: {source_id}.{dataset_id}")
    contract = _load_raw_contract(project_root, raw_contract, source_id)
    return pattern, raw_contract, contract


def _runtime_lifecycle_sql(action: str, names) -> str:
    verb = "SUSPEND" if action == "pause" else "RESUME"
    if names.execution_model == "stream_task":
        if not names.task:
            return "-- Stream/Task implementation has no generated Task; manage readiness explicitly.\n"
        return f"ALTER TASK {names.task} {verb};\n"
    if names.execution_model == "dynamic_table":
        if not names.dynamic_table:
            raise ValueError("dynamic_table implementation has no runtime relation")
        return f"ALTER DYNAMIC TABLE {names.dynamic_table} {verb};\n"
    if names.execution_model == "batch_sql":
        return "-- Batch SQL has no Framework-owned scheduler to pause/resume. Coordinate the external scheduler explicitly.\n"
    return "-- CUSTOM pipeline: pause/resume the domain-owned orchestrator explicitly here.\n"


def _retire_runtime_sql(names) -> str:
    if names.execution_model == "stream_task" and names.task:
        return f"ALTER TASK {names.task} SUSPEND;"
    if names.execution_model == "dynamic_table" and names.dynamic_table:
        return f"ALTER DYNAMIC TABLE {names.dynamic_table} SUSPEND;"
    if names.execution_model == "batch_sql":
        return f"-- {names.version}: batch_sql has no Framework-owned scheduler to suspend."
    return f"-- {names.version}: custom runtime; stop its domain-owned orchestrator manually."


def generate_lifecycle_scripts(
    *,
    project_root: Path,
    source_id: str,
    dataset_id: str,
    action: str,
    operation_id: str,
    version: str | None = None,
    output_root: Path | None = None,
) -> LifecycleScriptsResult:
    project_root = project_root.resolve()
    action = action.lower()
    if action not in LIFECYCLE_ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(sorted(LIFECYCLE_ACTIONS))}")
    if not _OPERATION_ID.fullmatch(operation_id):
        raise ValueError("operation_id must match ^[a-z][a-z0-9_-]{1,63}$")

    pattern, _, contract = _context(project_root, source_id, dataset_id)
    entity = str(contract["entity"])
    dataset_key = f"{source_id}.{dataset_id}"

    root = (output_root or project_root / "operations" / "lifecycle").resolve()
    destination = root / source_id / dataset_id / operation_id
    if destination.exists():
        return LifecycleScriptsResult(source_id, dataset_id, action, operation_id, destination, False)

    if action in {"pause", "resume"}:
        if version is None:
            raise ValueError(f"{action} requires an explicit --version; never guess the active implementation")
        validate_version(version)
        if version not in existing_versions(project_root, source_id, dataset_id):
            raise FileNotFoundError(f"version implementation not found: {source_id}.{dataset_id} {version}")
        execution = load_version_execution(project_root, source_id, dataset_id, version, pattern=pattern)
        names = build_names(
            source_id=source_id,
            dataset_id=dataset_id,
            pattern=pattern,
            entity=entity,
            version=version,
            execution_model=execution.execution_model,
        )
        runtime_sql = _runtime_lifecycle_sql(action, names)
        enabled = "FALSE" if action == "pause" else "TRUE"
        lifecycle_status = "PAUSED" if action == "pause" else "ACTIVE"
        sql = f"""-- {action.upper()} logical dataset {dataset_key} using explicit implementation {version}.
-- Execution model: {execution.execution_model}
-- Generated for review. `esf` does not execute this file.
-- Requires CONTROL lifecycle migration and execution-model migration 090.

{runtime_sql}
UPDATE CONTROL.DATASET
SET ENABLED = {enabled},
    LIFECYCLE_STATUS = '{lifecycle_status}',
    UPDATED_AT = CURRENT_TIMESTAMP()
WHERE DATASET_ID = '{dataset_key}';

CALL CONTROL.EVALUATE_DOMAIN_HEALTH();
"""
        readme = f"""# {action.title()} {dataset_key}

Operation id: `{operation_id}`  
Implementation: `{version}`  
Execution model: `{execution.execution_model}`

Review `operation.sql` before execution. This directory is immutable from the Framework's perspective after creation.
"""
    else:
        if version is not None:
            raise ValueError("decommission operates on the logical dataset; do not pass --version")
        versions = existing_versions(project_root, source_id, dataset_id)
        if not versions:
            raise FileNotFoundError(f"dataset implementation not found: {source_id}.{dataset_id}")
        suspends: list[str] = []
        for item in versions:
            execution = load_version_execution(project_root, source_id, dataset_id, item, pattern=pattern)
            names = build_names(
                source_id=source_id,
                dataset_id=dataset_id,
                pattern=pattern,
                entity=entity,
                version=item,
                execution_model=execution.execution_model,
            )
            suspends.append(_retire_runtime_sql(names))
        sql = f"""-- SOFT DECOMMISSION logical dataset {dataset_key}.
-- Generated for review. `esf` does not execute this file.
-- This intentionally does NOT DROP Silver history, published views, Bronze, or control-plane audit rows.
-- Physical cleanup is a separate approved retention/governance action.

{chr(10).join(suspends)}

UPDATE CONTROL.DATASET
SET ENABLED = FALSE,
    LIFECYCLE_STATUS = 'DECOMMISSIONED',
    CANDIDATE_VERSION = NULL,
    UPDATED_AT = CURRENT_TIMESTAMP()
WHERE DATASET_ID = '{dataset_key}';

UPDATE CONTROL.DATASET_VERSION
SET STATUS = 'RETIRED',
    RETIRED_AT = COALESCE(RETIRED_AT, CURRENT_TIMESTAMP()),
    UPDATED_AT = CURRENT_TIMESTAMP()
WHERE DATASET_ID = '{dataset_key}'
  AND STATUS <> 'RETIRED';

CALL CONTROL.EVALUATE_DOMAIN_HEALTH();

-- Deliberately absent:
-- DROP TABLE ...
-- DROP VIEW ...
-- DROP STREAM ...
-- DROP DYNAMIC TABLE ...
-- DELETE FROM CONTROL ...
"""
        readme = f"""# Soft decommission {dataset_key}

Operation id: `{operation_id}`

This is phase 1 of decommission only: stop every known version according to its execution model and mark the logical dataset `DECOMMISSIONED` while preserving published data and audit evidence.
"""

    destination.mkdir(parents=True, exist_ok=False)
    (destination / "README.md").write_text(readme, encoding="utf-8")
    (destination / "operation.sql").write_text(sql, encoding="utf-8")
    return LifecycleScriptsResult(source_id, dataset_id, action, operation_id, destination, True)
