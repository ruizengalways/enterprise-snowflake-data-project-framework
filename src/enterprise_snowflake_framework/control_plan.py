from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

KNOWN_CONTROL_SQL = (
    "control_plane/sql/001_objects.sql",
    "control_plane/sql/010_observability_views.sql",
    "control_plane/sql/020_refresh_health.sql",
    "control_plane/sql/030_sla_incident_lifecycle.sql",
    "control_plane/sql/040_health_task.sql",
    "control_plane/sql/050_dataset_lifecycle_status.sql",
)


@dataclass(frozen=True)
class ControlPlan:
    manifest: Path
    known_files_present: tuple[str, ...]
    known_files_missing: tuple[str, ...]
    manifest_entries: tuple[str, ...]
    missing_from_manifest: tuple[str, ...]
    unknown_manifest_entries: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.known_files_missing and not self.missing_from_manifest


def _manifest_entries(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        return ()
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.split("#", 1)[0].strip()
        if value:
            entries.append(value)
    return tuple(entries)


def build_control_plan(project_root: Path) -> ControlPlan:
    project_root = project_root.resolve()
    manifest = project_root / "control_plane" / "deploy_manifest.txt"
    entries = _manifest_entries(manifest)
    present = tuple(path for path in KNOWN_CONTROL_SQL if (project_root / path).is_file())
    missing = tuple(path for path in KNOWN_CONTROL_SQL if not (project_root / path).is_file())
    missing_manifest = tuple(path for path in present if path not in entries)
    unknown = tuple(path for path in entries if path not in KNOWN_CONTROL_SQL)
    return ControlPlan(
        manifest=manifest,
        known_files_present=present,
        known_files_missing=missing,
        manifest_entries=entries,
        missing_from_manifest=missing_manifest,
        unknown_manifest_entries=unknown,
    )
