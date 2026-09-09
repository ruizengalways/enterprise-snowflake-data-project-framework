from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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


def _task_sql(action: str, task: str, pattern: str) -> str:
    if pattern == "custom":
        return "-- CUSTOM pipeline: pause/resume the domain-owned orchestrator explicitly here.\n"
    verb = "SUSPEND" if action == "pause" else "RESUME"
    return f"ALTER TASK {task} {verb};\n"


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
        names = build_names(
            source_id=source_id,
            dataset_id=dataset_id,
            pattern=pattern,
            entity=entity,
            version=version,
        )
        task = _task_sql(action, names.task, pattern)
        enabled = "FALSE" if action == "pause" else "TRUE"
        lifecycle_status = "PAUSED" if action == "pause" else "ACTIVE"
        sql = f"""-- {action.upper()} logical dataset {dataset_key} using explicit implementation {version}.
-- Generated for review. `esf` does not execute this file.
-- Requires CONTROL lifecycle migration 050_dataset_lifecycle_status.sql.
-- If the domain changed task/orchestrator names after scaffolding, edit this script before execution.

{task}
UPDATE CONTROL.DATASET
SET ENABLED = {enabled},
    LIFECYCLE_STATUS = '{lifecycle_status}',
    UPDATED_AT = CURRENT_TIMESTAMP()
WHERE DATASET_ID = '{dataset_key}';

-- Re-evaluate health after the approved lifecycle change.
CALL CONTROL.EVALUATE_DOMAIN_HEALTH();
"""
        readme = f"""# {action.title()} {dataset_key}

Operation id: `{operation_id}`  
Implementation: `{version}`

Review `operation.sql` before execution. This directory is immutable from the Framework's perspective after creation.

For `resume`, confirm the selected version is the intended active implementation and that its Task/readiness model is valid before running the SQL.
"""
    else:
        if version is not None:
            raise ValueError("decommission operates on the logical dataset; do not pass --version")
        versions = existing_versions(project_root, source_id, dataset_id)
        if not versions:
            raise FileNotFoundError(f"dataset implementation not found: {source_id}.{dataset_id}")
        suspends: list[str] = []
        for item in versions:
            names = build_names(
                source_id=source_id,
                dataset_id=dataset_id,
                pattern=pattern,
                entity=entity,
                version=item,
            )
            if pattern == "custom":
                suspends.append(f"-- {item}: CUSTOM pipeline; stop its domain-owned orchestrator manually.")
            else:
                suspends.append(f"ALTER TASK {names.task} SUSPEND;")
        sql = f"""-- SOFT DECOMMISSION logical dataset {dataset_key}.
-- Generated for review. `esf` does not execute this file.
-- Requires CONTROL lifecycle migration 050_dataset_lifecycle_status.sql.
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
-- DELETE FROM CONTROL ...
"""
        readme = f"""# Soft decommission {dataset_key}

Operation id: `{operation_id}`

This is phase 1 of decommission only: stop processing and mark the logical dataset `DECOMMISSIONED` while preserving published data and audit evidence.

After the agreed retention/rollback window, perform physical cleanup in a separately reviewed change. Do not combine destructive cleanup with the initial decommission cutover.
"""

    destination.mkdir(parents=True, exist_ok=False)
    (destination / "README.md").write_text(readme, encoding="utf-8")
    (destination / "operation.sql").write_text(sql, encoding="utf-8")
    return LifecycleScriptsResult(source_id, dataset_id, action, operation_id, destination, True)
