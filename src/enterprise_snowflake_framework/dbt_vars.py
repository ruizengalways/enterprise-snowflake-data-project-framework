from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
    When execution context is supplied, each dataset receives a canonical
    dataset-level Snowflake QUERY_TAG. Arbitrary SQL/business-rule fields are
    never exposed through this bridge.
    """
    project_root = project_root.resolve()
    errors = validate_project_tree(project_root, schema_dir.resolve())
    if errors:
        raise MetadataValidationError("\n".join(errors))

    project = load_document(project_root / "config" / "project.yml")["project"]
    datasets: dict[str, dict[str, Any]] = {}

    for path in sorted((project_root / "config" / "datasets").glob("*.y*ml")):
        dataset = load_document(path)["dataset"]
        dataset_id = dataset["id"]
        raw_contract = load_document(project_root / dataset["raw_contract"])["contract"]
        technical = {
            key: value
            for key, value in dataset.items()
            if key
            in {
                "id",
                "owner_team",
                "raw_contract",
                "load_strategy",
                "implementation",
                "business_key",
                "watermark_column",
                "freshness",
                "reconciliation",
            }
        }
        technical["source_system"] = raw_contract["source_system"]
        if raw_contract.get("capture"):
            technical["capture"] = raw_contract["capture"]

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
    }
