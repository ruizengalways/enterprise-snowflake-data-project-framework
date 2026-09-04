from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_DATASET_KEYS = (
    "id",
    "owner_team",
    "raw_contract",
    "load_strategy",
    "implementation",
    "business_key",
    "watermark_column",
    "scd2",
    "freshness",
    "reconciliation",
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
    """Serialize machine configuration deterministically for audit hashing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_dataset_config_snapshot(
    dataset_document: Mapping[str, Any],
    raw_contract_document: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a bounded, deterministic snapshot of Git-owned technical metadata.

    Runtime context such as run_id/query_tag is deliberately excluded. The
    snapshot records only validated configuration that should be reproducible
    from a Git revision.
    """
    dataset = dataset_document["dataset"]
    contract = raw_contract_document["contract"]
    payload = {
        "dataset": {key: dataset[key] for key in _DATASET_KEYS if key in dataset},
        "source_contract": {
            key: contract[key] for key in _SOURCE_CONTRACT_KEYS if key in contract
        },
        "raw_contract_schema_version": raw_contract_document["schema_version"],
    }
    config_json = canonical_json(payload)
    return {
        "config_schema_version": dataset_document["schema_version"],
        "config_hash": sha256_hex(config_json),
        "config_json": config_json,
    }
