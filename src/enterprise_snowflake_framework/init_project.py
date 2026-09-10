from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIRECTORIES = (
    "config/sources",
    "contracts/raw",
    "ingestion",
    "ingestion/examples",
    "silver_processing",
    "control_plane/sql",
    "dbt/macros",
    "dbt/models/sources",
    "dbt/models/marts",
    "dbt/models/semantic",
    "dbt/tests",
    "operations/reset",
    "operations/replay",
    "operations/backfill",
    "operations/release",
    "operations/sla",
    "operations/lifecycle",
    "docs",
    ".github/workflows",
)

TRACKED_EMPTY_DIRECTORIES = (
    "config/sources",
    "contracts/raw",
    "dbt/models/sources",
    "dbt/models/marts",
    "dbt/models/semantic",
    "dbt/tests",
    "docs",
    ".github/workflows",
)

PROJECT_TEMPLATE_FILES = {
    "config/project.yml": "project.yml",
    "README.md": "README.md",
    "ingestion/README.md": "ingestion_README.md",
    "ingestion/RUN_EVIDENCE.md": "ingestion_RUN_EVIDENCE.md",
    "ingestion/examples/run_evidence.sql": "ingestion_run_evidence_example.sql",
    "control_plane/README.md": "control_plane_README.md",
    "control_plane/deploy_manifest.txt": "control_plane_deploy_manifest.txt",
    "control_plane/sql/001_objects.sql": "control_plane_001_objects.sql",
    "control_plane/sql/010_observability_views.sql": "control_plane_010_observability_views.sql",
    "control_plane/sql/020_refresh_health.sql": "control_plane_020_refresh_health.sql",
    "control_plane/sql/030_sla_incident_lifecycle.sql": "control_plane_030_sla_incident_lifecycle.sql",
    "control_plane/sql/040_health_task.sql": "control_plane_040_health_task.sql",
    "control_plane/sql/050_dataset_lifecycle_status.sql": "control_plane_050_dataset_lifecycle_status.sql",
    "control_plane/sql/060_run_evidence_api.sql": "control_plane_060_run_evidence_api.sql",
    "control_plane/sql/070_enterprise_health_export.sql": "control_plane_070_enterprise_health_export.sql",
    "dbt/README.md": "dbt_README.md",
    "dbt/dbt_project.yml": "dbt_project.yml",
    "dbt/profiles.yml": "profiles.yml",
    "dbt/macros/esf_observability.sql": "dbt_esf_observability.sql",
    "silver_processing/deploy_manifest.txt": "deploy_manifest.txt",
    "operations/replay/README.md": "replay_README.md",
    "operations/backfill/README.md": "backfill_README.md",
    "operations/reset/README.md": "reset_README.md",
    "operations/release/README.md": "release_README.md",
    "operations/sla/README.md": "sla_README.md",
    "operations/lifecycle/README.md": "lifecycle_README.md",
    "docs/DOMAIN_DECOMMISSION.md": "domain_decommission.md",
    "docs/ENTERPRISE_HEALTH_EXPORT.md": "enterprise_health_export.md",
}


@dataclass(frozen=True)
class InitProjectResult:
    project_root: Path
    created_directories: tuple[Path, ...]
    created_files: tuple[Path, ...]
    skipped_files: tuple[Path, ...]


def _template_root() -> Path:
    return Path(__file__).resolve().parent / "templates" / "project"


def _project_identity(project_root: Path) -> dict[str, str]:
    repository = project_root.name
    match = re.fullmatch(r"enterprise-snowflake-([a-z0-9-]+)-analytics", repository)
    if match:
        slug = match.group(1)
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", repository.lower()).strip("-") or "new-domain"
        repository = f"enterprise-snowflake-{slug}-analytics"
    code = slug.replace("-", "_").upper()[:32]
    if len(code) < 2:
        code = f"{code}_DOMAIN"[:32]
    return {
        "__PROJECT_CODE__": code,
        "__PROJECT_CODE_LOWER__": code.lower(),
        "__PROJECT_NAME__": f"{slug.replace('-', ' ').title()} analytics",
        "__PROJECT_REPOSITORY__": repository,
        "__OWNER_TEAM__": f"{slug}-data",
    }


def _render_template(path: Path, replacements: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    for marker, value in replacements.items():
        text = text.replace(marker, value)
    return text


def _write_if_missing(path: Path, text: str, created: list[Path], skipped: list[Path]) -> None:
    if path.exists():
        skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    created.append(path)


def initialize_project(project_root: Path, template_root: Path | None = None) -> InitProjectResult:
    project_root = project_root.resolve()
    project_root.mkdir(parents=True, exist_ok=True)

    created_directories: list[Path] = []
    created_files: list[Path] = []
    skipped_files: list[Path] = []

    for relative in PROJECT_DIRECTORIES:
        path = project_root / relative
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created_directories.append(path)

    root = (template_root or _template_root()).resolve()
    replacements = _project_identity(project_root)
    for destination_name, template_name in PROJECT_TEMPLATE_FILES.items():
        source = root / template_name
        if not source.is_file():
            raise FileNotFoundError(f"project template not found: {source}")
        _write_if_missing(
            project_root / destination_name,
            _render_template(source, replacements),
            created_files,
            skipped_files,
        )

    for relative in TRACKED_EMPTY_DIRECTORIES:
        _write_if_missing(project_root / relative / ".gitkeep", "", created_files, skipped_files)

    return InitProjectResult(
        project_root=project_root,
        created_directories=tuple(created_directories),
        created_files=tuple(created_files),
        skipped_files=tuple(skipped_files),
    )
