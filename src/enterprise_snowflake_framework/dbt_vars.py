from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .config_snapshot import build_dataset_config_snapshot
from .dataset_metadata import canonical_dataset
from .metadata_validation import MetadataValidationError, load_document, validate_project_tree
from .query_tags import build_query_tag


def build_dbt_vars(
    project_root: Path,
    schema_dir: Path,
    *,
    query_context: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Expose bounded technical metadata to dbt without compatibility aliases or business SQL."""
    project_root = project_root.resolve()
    errors = validate_project_tree(project_root, schema_dir.resolve())
    if errors:
        raise MetadataValidationError("\n".join(errors))

    project = load_document(project_root / "config" / "project.yml")["project"]
    datasets: dict[str, dict[str, Any]] = {}
    snapshots: dict[str, dict[str, Any]] = {}

    for path in sorted((project_root / "config" / "datasets").glob("*.y*ml")):
        document = load_document(path)
        dataset = canonical_dataset(document)
        dataset_id = dataset["id"]
        raw_document = None
        raw_contract = None
        if dataset.get("raw_contract"):
            raw_document = load_document(project_root / dataset["raw_contract"])
            raw_contract = raw_document["contract"]

        technical: dict[str, Any] = {"schema_version": 2, **dataset}
        if raw_contract:
            technical["source_system"] = raw_contract["source_system"]
            technical["source_contract"] = {
                "grain": raw_contract["grain"],
                "business_key": raw_contract["business_key"],
                "source_timestamp": raw_contract.get("source_timestamp"),
                "change_semantics": raw_contract["change_semantics"],
            }

        snapshots[dataset_id] = build_dataset_config_snapshot(document, raw_document)

        if query_context is not None:
            technical["query_tag"] = build_query_tag(
                {
                    "project": project["code"].lower(),
                    "environment": query_context.get("environment"),
                    "workload": query_context.get("workload"),
                    "source": raw_contract.get("source_system") if raw_contract else None,
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
