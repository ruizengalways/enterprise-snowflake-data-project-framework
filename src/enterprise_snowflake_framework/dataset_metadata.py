from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping


class DatasetMetadataError(ValueError):
    pass


_V1_STRATEGY_MAP: dict[str, tuple[str, str]] = {
    "full_refresh": ("full_refresh", "dbt_batch"),
    "append_only": ("append_only", "dbt_batch"),
    "incremental_merge": ("incremental_merge", "dbt_batch"),
    "scd1_merge": ("scd1", "dbt_batch"),
    "scd2_snapshot": ("scd2", "dbt_snapshot"),
    "scd2_merge": ("scd2", "dbt_batch"),
    "scd2_stream_task": ("scd2", "stream_task"),
}

_EXECUTION_COMPATIBILITY: dict[str, set[str]] = {
    "full_refresh": {"dbt_batch", "dynamic_table", "custom"},
    "append_only": {"dbt_batch", "stream_task", "custom"},
    "incremental_merge": {"dbt_batch", "stream_task", "custom"},
    "scd1": {"dbt_batch", "dynamic_table", "stream_task", "custom"},
    "scd2": {"dbt_batch", "dbt_snapshot", "stream_task", "custom"},
    "custom": {"custom"},
}


def normalize_dataset_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical v2-shaped runtime view of dataset metadata.

    Schema v1 remains supported as a migration input. The normalized structure
    deliberately separates target semantics (`load.strategy`) from the
    execution mechanism (`load.execution.mode`).
    """
    version = document.get("schema_version")
    dataset = document.get("dataset")
    if not isinstance(dataset, Mapping):
        raise DatasetMetadataError("dataset metadata must contain an object at dataset")

    if version == 1:
        return _normalize_v1(dataset)
    if version == 2:
        return _normalize_v2(dataset)
    raise DatasetMetadataError(f"unsupported dataset schema_version: {version!r}")


def _normalize_v1(dataset: Mapping[str, Any]) -> dict[str, Any]:
    legacy_strategy = str(dataset.get("load_strategy", ""))
    if legacy_strategy not in _V1_STRATEGY_MAP:
        raise DatasetMetadataError(f"unsupported v1 load_strategy: {legacy_strategy!r}")

    strategy, mode = _V1_STRATEGY_MAP[legacy_strategy]
    if dataset.get("implementation", "standard") == "custom":
        mode = "custom"

    load: dict[str, Any] = {
        "strategy": strategy,
        "execution": {"mode": mode},
    }
    for key in ("business_key", "watermark_column", "scd2"):
        if key in dataset:
            load[key] = deepcopy(dataset[key])

    canonical = {
        "id": dataset["id"],
        "owner_team": dataset["owner_team"],
        "raw_contract": dataset["raw_contract"],
        "load": load,
    }
    for key in ("freshness", "reconciliation"):
        if key in dataset:
            canonical[key] = deepcopy(dataset[key])
    return canonical


def _normalize_v2(dataset: Mapping[str, Any]) -> dict[str, Any]:
    canonical = {
        "id": dataset["id"],
        "owner_team": dataset["owner_team"],
        "raw_contract": dataset["raw_contract"],
        "load": deepcopy(dataset["load"]),
    }
    for key in ("freshness", "reconciliation"):
        if key in dataset:
            canonical[key] = deepcopy(dataset[key])
    return canonical


def legacy_dataset_view(canonical: Mapping[str, Any]) -> dict[str, Any]:
    """Expose the legacy flat view used by existing validators/macros.

    This is a compatibility bridge, not the preferred public metadata shape.
    New framework code should read the canonical `load` object.
    """
    load = canonical["load"]
    strategy = load["strategy"]
    mode = load["execution"]["mode"]

    if strategy == "scd1":
        legacy_strategy = "scd1_merge"
    elif strategy == "scd2":
        if mode == "dbt_snapshot":
            legacy_strategy = "scd2_snapshot"
        elif mode == "stream_task":
            legacy_strategy = "scd2_stream_task"
        else:
            legacy_strategy = "scd2_merge"
    else:
        legacy_strategy = strategy

    value: dict[str, Any] = {
        "id": canonical["id"],
        "owner_team": canonical["owner_team"],
        "raw_contract": canonical["raw_contract"],
        "load_strategy": legacy_strategy,
        "implementation": "custom" if mode == "custom" else "standard",
    }
    for key in ("business_key", "watermark_column", "scd2"):
        if key in load:
            value[key] = deepcopy(load[key])
    for key in ("freshness", "reconciliation"):
        if key in canonical:
            value[key] = deepcopy(canonical[key])
    return value


def validate_execution_model(canonical: Mapping[str, Any], path: Path) -> list[str]:
    load = canonical["load"]
    strategy = load["strategy"]
    execution = load["execution"]
    mode = execution["mode"]
    errors: list[str] = []

    allowed = _EXECUTION_COMPATIBILITY.get(strategy, set())
    if mode not in allowed:
        errors.append(
            f"{path}: load.strategy {strategy} does not support execution.mode {mode}; "
            f"allowed: {', '.join(sorted(allowed))}"
        )

    if strategy == "custom" and mode != "custom":
        errors.append(f"{path}: load.strategy custom requires execution.mode=custom")

    if mode == "dynamic_table" and strategy == "scd2":
        errors.append(
            f"{path}: SCD2 history is not a dynamic-table execution mode; use dbt_batch, dbt_snapshot, "
            "stream_task, or custom"
        )

    return errors
