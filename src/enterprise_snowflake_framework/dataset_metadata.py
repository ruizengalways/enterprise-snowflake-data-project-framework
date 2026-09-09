from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping


class DatasetMetadataError(ValueError):
    pass


_ALLOWED_MATERIALIZATIONS = {
    "full_refresh": {"table", "view", "custom"},
    "append_only": {"table", "custom"},
    "incremental_merge": {"table", "custom"},
    "scd1": {"table", "custom"},
    "scd2": {"table", "snapshot", "custom"},
    "custom": {"table", "view", "snapshot", "custom"},
}


def canonical_dataset(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return the v2 dataset object without any compatibility normalization."""
    if document.get("schema_version") != 2:
        raise DatasetMetadataError("dataset schema_version must be 2")
    dataset = document.get("dataset")
    if not isinstance(dataset, Mapping):
        raise DatasetMetadataError("dataset metadata must contain an object at dataset")
    return deepcopy(dict(dataset))


def validate_runtime_model(dataset: Mapping[str, Any], path: Path) -> list[str]:
    """Validate only cross-axis technical constraints, never business SQL."""
    errors: list[str] = []
    load = dataset.get("load")
    materialization = dataset["materialization"]
    runtime = dataset["runtime"]
    materialization_type = materialization["type"]
    runtime_mode = runtime["mode"]

    if materialization_type == "dynamic_table":
        if runtime_mode != "snowflake_managed":
            errors.append(f"{path}: dynamic_table requires runtime.mode=snowflake_managed")
        if load and load.get("strategy") == "scd2":
            errors.append(f"{path}: stateful SCD2 history must not use dynamic_table materialization")

    if runtime_mode == "snowflake_managed" and materialization_type != "dynamic_table":
        errors.append(f"{path}: runtime.mode=snowflake_managed is reserved for dynamic_table datasets")

    if runtime_mode == "stream_task" and materialization_type == "view":
        errors.append(f"{path}: stream_task cannot maintain a view")

    if load:
        strategy = load["strategy"]
        allowed = _ALLOWED_MATERIALIZATIONS[strategy]
        if materialization_type not in allowed:
            errors.append(
                f"{path}: load.strategy {strategy} does not support materialization.type "
                f"{materialization_type}; allowed: {', '.join(sorted(allowed))}"
            )

    freshness = dataset.get("quality", {}).get("freshness")
    if freshness and freshness["warn_after_minutes"] > freshness["error_after_minutes"]:
        errors.append(f"{path}: quality.freshness warn_after_minutes must be <= error_after_minutes")

    return errors
