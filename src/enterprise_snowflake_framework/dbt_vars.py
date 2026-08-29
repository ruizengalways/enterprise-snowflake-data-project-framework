from __future__ import annotations

from pathlib import Path
from typing import Any

from .metadata_validation import MetadataValidationError, load_document, validate_project_tree


def build_dbt_vars(project_root: Path, schema_dir: Path) -> dict[str, Any]:
    """Build the bounded technical metadata exposed to dbt macros.

    Validation runs first so dbt never receives a partially valid metadata tree.
    The output intentionally excludes arbitrary SQL/business-rule fields.
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
        datasets[dataset_id] = {
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

    return {
        "esf_project": {
            "code": project["code"],
            "repository": project["repository"],
            "owner_team": project["owner_team"],
        },
        "esf_datasets": datasets,
    }
