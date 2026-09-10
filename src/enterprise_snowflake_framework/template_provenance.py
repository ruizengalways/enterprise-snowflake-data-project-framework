from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

# Keep this release identity explicit and deterministic. A contract test keeps it in sync
# with pyproject.toml. Generated files must not depend on wall-clock time or Git state.
FRAMEWORK_VERSION = "0.23.0"

VERSION_RE = re.compile(r"^v([1-9][0-9]*)$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class TemplateSpec:
    template_id: str
    revision: int
    artifact_contract: tuple[str, ...]

    @property
    def digest(self) -> str:
        material = {
            "contract": "esf-template-identity-v1",
            "template_id": self.template_id,
            "template_revision": self.revision,
            "artifact_contract": list(self.artifact_contract),
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class TemplateProvenance:
    framework_version: str
    template_id: str
    template_revision: int
    template_digest: str


@dataclass(frozen=True)
class TemplateAdvisory:
    advisory_id: str
    severity: str
    template_id: str
    affected_max_revision: int
    issue: str
    recommendation: str


@dataclass(frozen=True)
class UpgradePlanEntry:
    source_id: str
    dataset_id: str
    version: str
    status: str
    reason: str
    provenance: TemplateProvenance | None
    current_revision: int | None
    advisories: tuple[TemplateAdvisory, ...] = ()

    @property
    def dataset_key(self) -> str:
        return f"{self.source_id}.{self.dataset_id}"


@dataclass(frozen=True)
class UpgradePlan:
    project_root: Path
    entries: tuple[UpgradePlanEntry, ...]

    def render(self) -> str:
        lines = [
            "Template upgrade plan",
            f"Project: {self.project_root}",
            f"Framework: {FRAMEWORK_VERSION}",
            "",
        ]
        if not self.entries:
            lines.append("No scaffolded dataset versions found.")
        for entry in self.entries:
            lines.append(f"{entry.dataset_key} {entry.version}")
            if entry.provenance is None:
                lines.append("  template: UNKNOWN")
            else:
                lines.append(
                    f"  template: {entry.provenance.template_id} "
                    f"revision {entry.provenance.template_revision}"
                )
                lines.append(f"  generated_by: {entry.provenance.framework_version}")
                lines.append(f"  digest: {entry.provenance.template_digest}")
                if entry.current_revision is not None:
                    lines.append(f"  current_revision: {entry.current_revision}")
            lines.append(f"  status: {entry.status}")
            lines.append(f"  reason: {entry.reason}")
            for advisory in entry.advisories:
                lines.extend(
                    [
                        f"  ADVISORY {advisory.advisory_id}",
                        f"    severity: {advisory.severity}",
                        f"    issue: {advisory.issue}",
                        f"    recommended: {advisory.recommendation}",
                    ]
                )
            lines.append("")

        counts = {
            status: sum(1 for entry in self.entries if entry.status == status)
            for status in ("CURRENT", "UPDATE_AVAILABLE", "ADVISORY", "UNKNOWN", "UNVERIFIED")
        }
        lines.extend(
            [
                "Summary:",
                "  " + "  ".join(f"{name}={count}" for name, count in counts.items()),
                "",
                "No files changed.",
            ]
        )
        return "\n".join(lines) + "\n"


_STREAM_TASK_ARTIFACTS = (
    "version.yml",
    "001_objects.sql",
    "010_apply.sql",
    "015_replay.sql",
    "020_validate.sql",
    "025_compare.sql",
    "030_task.sql",
    "040_register.sql",
    "050_publish.sql",
    "060_policy.sql",
    "deploy_manifest.fragment.txt",
)
_DYNAMIC_TABLE_ARTIFACTS = (
    "version.yml",
    "001_dynamic_table.sql",
    "020_validate.sql",
    "025_compare.sql",
    "040_register.sql",
    "050_publish.sql",
    "060_policy.sql",
    "deploy_manifest.fragment.txt",
)
_BATCH_SQL_ARTIFACTS = (
    "version.yml",
    "001_objects.sql",
    "010_apply.sql",
    "015_replay.sql",
    "020_validate.sql",
    "025_compare.sql",
    "040_register.sql",
    "050_publish.sql",
    "060_policy.sql",
    "deploy_manifest.fragment.txt",
)
_CUSTOM_ARTIFACTS = (
    "version.yml",
    "001_objects.sql",
    "025_compare.sql",
    "040_register.sql",
    "050_publish.sql",
    "060_policy.sql",
    "deploy_manifest.fragment.txt",
)

# Historical revisions must stay here after a new revision is introduced. upgrade-plan
# verifies a declared digest against this registry; it never reverse-engineers old SQL.
# Revision 2 of the Stream/Task templates declares version-local Task operational policy.
_TEMPLATE_HISTORY: dict[str, dict[int, TemplateSpec]] = {
    "append_stream_task": {
        1: TemplateSpec("append_stream_task", 1, _STREAM_TASK_ARTIFACTS),
        2: TemplateSpec("append_stream_task", 2, _STREAM_TASK_ARTIFACTS),
    },
    "full_refresh_stream_task": {
        1: TemplateSpec("full_refresh_stream_task", 1, _STREAM_TASK_ARTIFACTS),
        2: TemplateSpec("full_refresh_stream_task", 2, _STREAM_TASK_ARTIFACTS),
    },
    "full_refresh_dynamic_table": {
        1: TemplateSpec("full_refresh_dynamic_table", 1, _DYNAMIC_TABLE_ARTIFACTS)
    },
    "full_refresh_batch_sql": {
        1: TemplateSpec("full_refresh_batch_sql", 1, _BATCH_SQL_ARTIFACTS)
    },
    "scd1_stream_task": {
        1: TemplateSpec("scd1_stream_task", 1, _STREAM_TASK_ARTIFACTS),
        2: TemplateSpec("scd1_stream_task", 2, _STREAM_TASK_ARTIFACTS),
    },
    "scd1_dynamic_table": {
        1: TemplateSpec("scd1_dynamic_table", 1, _DYNAMIC_TABLE_ARTIFACTS)
    },
    "scd2_stream_task": {
        1: TemplateSpec("scd2_stream_task", 1, _STREAM_TASK_ARTIFACTS),
        2: TemplateSpec("scd2_stream_task", 2, _STREAM_TASK_ARTIFACTS),
    },
    "custom_custom": {1: TemplateSpec("custom_custom", 1, _CUSTOM_ARTIFACTS)},
}

_TEMPLATE_BY_PATTERN_EXECUTION = {
    ("append", "stream_task"): "append_stream_task",
    ("full_refresh", "stream_task"): "full_refresh_stream_task",
    ("full_refresh", "dynamic_table"): "full_refresh_dynamic_table",
    ("full_refresh", "batch_sql"): "full_refresh_batch_sql",
    ("scd1", "stream_task"): "scd1_stream_task",
    ("scd1", "dynamic_table"): "scd1_dynamic_table",
    ("scd2", "stream_task"): "scd2_stream_task",
    ("custom", "custom"): "custom_custom",
}

# Intentionally empty until a real released template revision needs an advisory. Tests inject
# advisory fixtures so the matching contract is exercised without publishing a fake incident.
DEFAULT_ADVISORIES: tuple[TemplateAdvisory, ...] = ()


def current_template_provenance(pattern: str, execution_model: str) -> TemplateProvenance:
    template_id = _TEMPLATE_BY_PATTERN_EXECUTION.get((pattern, execution_model))
    if template_id is None:
        raise ValueError(
            f"no template provenance registered for pattern={pattern}, execution_model={execution_model}"
        )
    revisions = _TEMPLATE_HISTORY[template_id]
    revision = max(revisions)
    spec = revisions[revision]
    return TemplateProvenance(
        framework_version=FRAMEWORK_VERSION,
        template_id=template_id,
        template_revision=revision,
        template_digest=spec.digest,
    )


def attach_template_provenance(
    version_yaml: str, *, pattern: str, execution_model: str
) -> str:
    provenance = current_template_provenance(pattern, execution_model)
    marker = f"  execution_model: {execution_model}"
    lines = version_yaml.rstrip("\n").splitlines()
    try:
        index = lines.index(marker)
    except ValueError as exc:
        raise ValueError("version YAML is missing its execution_model line") from exc
    block = [
        "  provenance:",
        f"    framework_version: {provenance.framework_version}",
        f"    template_id: {provenance.template_id}",
        f"    template_revision: {provenance.template_revision}",
        f"    template_digest: {provenance.template_digest}",
    ]
    return "\n".join(lines[: index + 1] + block + lines[index + 1 :]) + "\n"


def _declared_provenance(path: Path) -> tuple[TemplateProvenance | None, str | None]:
    if not path.is_file():
        return None, "version.yml is missing; provenance is UNKNOWN and is not inferred from SQL"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, f"version.yml cannot be read: {exc}"
    version = document.get("version") if isinstance(document, dict) else None
    provenance = version.get("provenance") if isinstance(version, dict) else None
    if not isinstance(provenance, dict):
        return None, "provenance is absent; template revision is UNKNOWN and is not inferred from SQL"
    try:
        declared = TemplateProvenance(
            framework_version=str(provenance["framework_version"]),
            template_id=str(provenance["template_id"]),
            template_revision=int(provenance["template_revision"]),
            template_digest=str(provenance["template_digest"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"provenance is malformed: {exc}"
    if not declared.framework_version or not declared.template_id or declared.template_revision < 1:
        return None, "provenance is malformed: identity fields must be non-empty and revision >= 1"
    if not DIGEST_RE.fullmatch(declared.template_digest):
        return None, "provenance is malformed: template_digest must be sha256:<64 lowercase hex>"
    return declared, None


def _version_files(dataset_root: Path) -> Iterable[tuple[str, Path]]:
    if not dataset_root.is_dir():
        return ()
    found: list[tuple[str, Path]] = [("v1", dataset_root / "version.yml")]
    versions_root = dataset_root / "versions"
    if versions_root.is_dir():
        for child in versions_root.iterdir():
            if child.is_dir() and VERSION_RE.fullmatch(child.name):
                found.append((child.name, child / "version.yml"))
    return tuple(sorted(found, key=lambda item: int(VERSION_RE.fullmatch(item[0]).group(1))))


def _evaluate_version(
    *,
    source_id: str,
    dataset_id: str,
    version: str,
    version_path: Path,
    advisories: tuple[TemplateAdvisory, ...],
) -> UpgradePlanEntry:
    provenance, problem = _declared_provenance(version_path)
    if provenance is None:
        return UpgradePlanEntry(
            source_id=source_id,
            dataset_id=dataset_id,
            version=version,
            status="UNKNOWN",
            reason=problem or "provenance is unavailable",
            provenance=None,
            current_revision=None,
        )

    history = _TEMPLATE_HISTORY.get(provenance.template_id)
    if history is None:
        return UpgradePlanEntry(
            source_id=source_id,
            dataset_id=dataset_id,
            version=version,
            status="UNKNOWN",
            reason="declared template_id is not present in this Framework registry",
            provenance=provenance,
            current_revision=None,
        )
    spec = history.get(provenance.template_revision)
    current_revision = max(history)
    if spec is None:
        return UpgradePlanEntry(
            source_id=source_id,
            dataset_id=dataset_id,
            version=version,
            status="UNKNOWN",
            reason="declared template revision is not present in this Framework registry",
            provenance=provenance,
            current_revision=current_revision,
        )
    if provenance.template_digest != spec.digest:
        return UpgradePlanEntry(
            source_id=source_id,
            dataset_id=dataset_id,
            version=version,
            status="UNVERIFIED",
            reason="declared template digest does not match the immutable registry identity",
            provenance=provenance,
            current_revision=current_revision,
        )

    matched = tuple(
        advisory
        for advisory in advisories
        if advisory.template_id == provenance.template_id
        and provenance.template_revision <= advisory.affected_max_revision
    )
    if matched:
        return UpgradePlanEntry(
            source_id=source_id,
            dataset_id=dataset_id,
            version=version,
            status="ADVISORY",
            reason=f"{len(matched)} advisory(s) affect this declared template revision",
            provenance=provenance,
            current_revision=current_revision,
            advisories=matched,
        )
    if provenance.template_revision < current_revision:
        return UpgradePlanEntry(
            source_id=source_id,
            dataset_id=dataset_id,
            version=version,
            status="UPDATE_AVAILABLE",
            reason="a newer registered template revision exists; no advisory marks this revision unsafe",
            provenance=provenance,
            current_revision=current_revision,
        )
    return UpgradePlanEntry(
        source_id=source_id,
        dataset_id=dataset_id,
        version=version,
        status="CURRENT",
        reason="declared template identity matches the current registered revision",
        provenance=provenance,
        current_revision=current_revision,
    )


def build_upgrade_plan(
    project_root: Path,
    *,
    advisories: Iterable[TemplateAdvisory] | None = None,
) -> UpgradePlan:
    project_root = project_root.resolve()
    source_root = project_root / "config" / "sources"
    selected_advisories = tuple(DEFAULT_ADVISORIES if advisories is None else advisories)
    entries: list[UpgradePlanEntry] = []
    if not source_root.is_dir():
        raise FileNotFoundError(f"source manifest directory not found: {source_root}")

    for manifest_path in sorted(source_root.glob("*.yml")):
        document = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("source"), dict):
            raise ValueError(f"invalid source manifest: {manifest_path}")
        source_id = str(document["source"].get("id") or manifest_path.stem)
        datasets = document.get("datasets")
        if not isinstance(datasets, dict):
            raise ValueError(f"invalid source manifest datasets: {manifest_path}")
        for dataset_id in sorted(datasets):
            dataset_root = project_root / "silver_processing" / source_id / str(dataset_id)
            for version, version_path in _version_files(dataset_root):
                entries.append(
                    _evaluate_version(
                        source_id=source_id,
                        dataset_id=str(dataset_id),
                        version=version,
                        version_path=version_path,
                        advisories=selected_advisories,
                    )
                )

    entries.sort(
        key=lambda entry: (
            entry.source_id,
            entry.dataset_id,
            int(VERSION_RE.fullmatch(entry.version).group(1)),
        )
    )
    return UpgradePlan(project_root=project_root, entries=tuple(entries))
