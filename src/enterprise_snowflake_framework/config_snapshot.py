from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_DATASET_KEYS = (
    "id",
    "owner_team",
    "raw_contract",
    "load",
    "materialization",
    "runtime",
    "compute",
    "quality",
)
_SOURCE_CONTRACT_KEYS = (
    "source_system",
    "entity",
    "grain",
    "business_key",
    "source_timestamp",
    "change_semantics",
    "capture",
    "cadence",
    "retention_days",
    "breaking_change_policy",
)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_dataset_config_snapshot(
    dataset_document: Mapping[str, Any], raw_contract_document: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Snapshot Git-owned processing config; runtime state and connector checkpoints are excluded."""
    if dataset_document.get("schema_version") != 2:
        raise ValueError("dataset config snapshots require schema_version 2")
    dataset = dataset_document["dataset"]
    payload: dict[str, Any] = {
        "dataset": {key: dataset[key] for key in _DATASET_KEYS if key in dataset},
        "dataset_schema_version": 2,
    }
    if raw_contract_document is not None:
        contract = raw_contract_document["contract"]
        payload["source_contract"] = {
            key: contract[key] for key in _SOURCE_CONTRACT_KEYS if key in contract
        }
        payload["raw_contract_schema_version"] = raw_contract_document["schema_version"]
    config_json = canonical_json(payload)
    return {
        "config_schema_version": 2,
        "config_hash": sha256_hex(config_json),
        "config_json": config_json,
    }
