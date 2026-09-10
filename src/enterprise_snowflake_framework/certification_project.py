from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .init_project import initialize_project
from .scaffold import scaffold_pipeline
from .source_management import add_source
from .versioning import scaffold_version


@dataclass(frozen=True)
class CertificationProject:
    root: Path
    fixture: dict[str, Any]
    source_id: str
    project_git_sha: str


def load_certification_fixture(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError(f"invalid certification fixture: {path}")
    source_id = document.get("source_id")
    datasets = document.get("datasets")
    if not isinstance(source_id, str) or not isinstance(datasets, dict):
        raise ValueError(f"certification fixture must define source_id and datasets: {path}")
    expected_patterns = {"append", "scd1", "scd2", "full_refresh"}
    actual_patterns = {
        str(spec.get("pattern"))
        for spec in datasets.values()
        if isinstance(spec, dict)
    }
    missing = expected_patterns - actual_patterns
    if missing:
        raise ValueError(f"certification fixture missing standard patterns: {sorted(missing)}")
    return document


def _run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        details = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        raise RuntimeError(details or f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-m", message)
    sha = _run_git(root, "rev-parse", "HEAD")
    if len(sha) != 40:
        raise RuntimeError(f"unexpected certification project Git SHA: {sha}")
    return sha


def _append_fragment(global_manifest: Path, fragment: Path) -> None:
    existing = global_manifest.read_text(encoding="utf-8")
    existing_paths = {
        raw.split("#", 1)[0].strip()
        for raw in existing.splitlines()
        if raw.split("#", 1)[0].strip()
    }
    additions: list[str] = []
    for raw in fragment.read_text(encoding="utf-8").splitlines():
        value = raw.split("#", 1)[0].strip()
        if value and value not in existing_paths:
            additions.append(value)
            existing_paths.add(value)
    if additions:
        global_manifest.write_text(existing.rstrip() + "\n" + "\n".join(additions) + "\n", encoding="utf-8")


def build_certification_project(root: Path, fixture_path: Path) -> CertificationProject:
    root = root.resolve()
    fixture = load_certification_fixture(fixture_path.resolve())
    source_id = str(fixture["source_id"])
    owner = str(fixture.get("owner") or "framework-cert")

    initialize_project(root)
    add_source(root, source_id)

    datasets = fixture["datasets"]
    manifest_datasets: dict[str, dict[str, str]] = {}
    for dataset_id, spec in datasets.items():
        if not isinstance(spec, dict):
            raise ValueError(f"invalid certification dataset fixture: {dataset_id}")
        pattern = str(spec["pattern"])
        contract = spec.get("contract")
        if not isinstance(contract, dict):
            raise ValueError(f"certification dataset missing contract: {dataset_id}")
        contract_path = root / "contracts" / "raw" / source_id / f"{dataset_id}.yml"
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_text(
            yaml.safe_dump({"schema_version": 2, "contract": contract}, sort_keys=False),
            encoding="utf-8",
        )
        manifest_datasets[str(dataset_id)] = {
            "pattern": pattern,
            "raw_contract": f"contracts/raw/{source_id}/{dataset_id}.yml",
        }

    source_manifest = {
        "schema_version": 1,
        "source": {"id": source_id, "owner": owner},
        "datasets": manifest_datasets,
    }
    (root / "config" / "sources" / f"{source_id}.yml").write_text(
        yaml.safe_dump(source_manifest, sort_keys=False),
        encoding="utf-8",
    )

    global_manifest = root / "silver_processing" / "deploy_manifest.txt"
    for dataset_id, spec in datasets.items():
        destination = scaffold_pipeline(
            project_root=root,
            source_id=source_id,
            pattern=str(spec["pattern"]),
            dataset_id=str(dataset_id),
        ).destination
        _append_fragment(global_manifest, destination / "deploy_manifest.fragment.txt")

    _run_git(root, "init", "-b", "main")
    _run_git(root, "config", "user.name", "ESF Snowflake Certification")
    _run_git(root, "config", "user.email", "esf-certification@example.invalid")
    project_sha = _commit(root, "certification fixture v1")
    return CertificationProject(
        root=root,
        fixture=fixture,
        source_id=source_id,
        project_git_sha=project_sha,
    )


def _single_dataset_for_pattern(project: CertificationProject, pattern: str) -> str:
    matches = [
        str(dataset_id)
        for dataset_id, spec in project.fixture["datasets"].items()
        if isinstance(spec, dict) and spec.get("pattern") == pattern
    ]
    if len(matches) != 1:
        raise ValueError(f"canonical certification fixture must contain exactly one {pattern} dataset")
    return matches[0]


def _add_candidate(
    project: CertificationProject,
    *,
    pattern: str,
    version: str,
    execution_model: str,
) -> CertificationProject:
    dataset_id = _single_dataset_for_pattern(project, pattern)
    destination = scaffold_version(
        project_root=project.root,
        source_id=project.source_id,
        dataset_id=dataset_id,
        version=version,
        execution_model=execution_model,
        target_lag="1 minute" if execution_model == "dynamic_table" else None,
        refresh_mode="incremental" if execution_model == "dynamic_table" else None,
    ).destination
    _append_fragment(
        project.root / "silver_processing" / "deploy_manifest.txt",
        destination / "deploy_manifest.fragment.txt",
    )
    project_sha = _commit(
        project.root,
        f"certification fixture {dataset_id} {version} {execution_model}",
    )
    return CertificationProject(
        root=project.root,
        fixture=project.fixture,
        source_id=project.source_id,
        project_git_sha=project_sha,
    )


def add_scd2_candidate(project: CertificationProject, version: str = "v2") -> CertificationProject:
    return _add_candidate(
        project,
        pattern="scd2",
        version=version,
        execution_model="stream_task",
    )


def add_scd1_dynamic_table_candidate(
    project: CertificationProject, version: str = "v2"
) -> CertificationProject:
    return _add_candidate(
        project,
        pattern="scd1",
        version=version,
        execution_model="dynamic_table",
    )
