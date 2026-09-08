from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .config_snapshot import build_dataset_config_snapshot
from .dataset_metadata import legacy_dataset_view, normalize_dataset_document
from .metadata_validation import MetadataValidationError, load_document, validate_project_tree
from .query_tags import build_query_tag


def build_dbt_vars(
    project_root: Path,
    schema_dir: Path,
    *,
    query_context: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build the bounded technical metadata exposed to dbt macros.

    Validation runs first so dbt never receives a partially valid metadata tree.
    Static Git configuration snapshots are produced separately from runtime
    query context so run IDs/query tags never change the deployment audit hash.
    Arbitrary SQL/business-rule fields are never exposed through this bridge.

    Dataset schema v2 is canonical. A small set of legacy flat aliases remains
    during migration so existing projects do not need a flag-day upgrade.
    """
    project_root = project_root.resolve()
    errors = validate_project_tree(project_root, schema_dir.resolve())
    if errors:
        raise MetadataValidationError("\n".join(errors))

    project = load_document(project_root / "config" / "project.yml")["project"]
    datasets: dict[str, dict[str, Any]] = {}
    snapshots: dict[str, dict[str, Any]] = {}

    for path in sorted((project_root / "config" / "datasets").glob("*.y*ml")):
        dataset_document = load_document(path)
        canonical = normalize_dataset_document(dataset_document)
        legacy = legacy_dataset_view(canonical)
        dataset_id = canonical["id"]
        raw_contract_document = load_document(project_root / canonical["raw_contract"])
        raw_contract = raw_contract_document["contract"]

        technical: dict[str, Any] = {
            "schema_version": dataset_document["schema_version"],
            "id": canonical["id"],
            "owner_team": canonical["owner_team"],
            "raw_contract": canonical["raw_contract"],
            "load": canonical["load"],
        }
        for key in ("freshness", "reconciliation"):
            if key in canonical:
                technical[key] = canonical[key]

        # Temporary compatibility aliases. New macros should use `load`.
        for key in (
            "load_strategy",
            "implementation",
            "business_key",
            "watermark_column",
            "scd2",
        ):
            if key in legacy:
                technical[key] = legacy[key]

        technical["source_system"] = raw_contract["source_system"]
        if raw_contract.get("capture"):
            technical["capture"] = raw_contract["capture"]

        snapshots[dataset_id] = build_dataset_config_snapshot(
            dataset_document,
            raw_contract_document,
        )

        if query_context is not None:
            technical["query_tag"] = build_query_tag(
                {
                    "project": project["code"].lower(),
                    "environment": query_context.get("environment"),
                    "workload": query_context.get("workload"),
                    "source": raw_contract.get("source_system"),
                    "dataset": dataset_id,
                    "run_id": query_context.get("run_id"),
                    "git_sha": query_context.get("git_sha"),
                    "pr_number": query_context.get("pr_number"),
                    "operation": "dbt_model",
                }
            )

        datasets[dataset_id] = technical

    return {
        "esf_project": {
            "code": project["code"],
            "repository": project["repository"],
            "owner_team": project["owner_team"],
        },
        "esf_datasets": datasets,
        "esf_dataset_snapshots": snapshots,
    }
