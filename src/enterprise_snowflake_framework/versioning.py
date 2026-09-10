from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .execution_model import load_version_execution, validate_execution_model
from .pipeline_sql import build_names, render_release_sql
from .scaffold import _load_raw_contract, render_implementation_files
from .source_management import load_source_manifest

VERSION_RE = re.compile(r"^v([1-9][0-9]*)$")


@dataclass(frozen=True)
class ScaffoldVersionResult:
    source_id: str
    dataset_id: str
    version: str
    destination: Path
    created: bool


@dataclass(frozen=True)
class ReleaseScriptsResult:
    source_id: str
    dataset_id: str
    from_version: str
    to_version: str
    destination: Path
    created: bool
    files: tuple[Path, ...]


def validate_version(version: str) -> int:
    match = VERSION_RE.fullmatch(version)
    if not match:
        raise ValueError("version must match v1, v2, ...")
    return int(match.group(1))


def _dataset_context(project_root: Path, source_id: str, dataset_id: str) -> tuple[dict, dict, str, str]:
    manifest = load_source_manifest(project_root, source_id)
    config = manifest["datasets"].get(dataset_id)
    if not isinstance(config, dict):
        raise KeyError(f"dataset is not declared in source manifest: {source_id}.{dataset_id}")
    pattern = config.get("pattern")
    raw_contract = config.get("raw_contract")
    if not isinstance(pattern, str) or not isinstance(raw_contract, str):
        raise ValueError(f"invalid source manifest dataset entry: {source_id}.{dataset_id}")
    return manifest, config, pattern, raw_contract


def scaffold_version(
    *,
    project_root: Path,
    source_id: str,
    dataset_id: str,
    version: str,
    execution_model: str = "stream_task",
    target_lag: str | None = None,
    warehouse: str | None = None,
    refresh_mode: str | None = None,
    template_root: Path | None = None,
) -> ScaffoldVersionResult:
    project_root = project_root.resolve()
    number = validate_version(version)
    if number == 1:
        raise ValueError("v1 is the initial dataset implementation; scaffold candidate versions from v2 onward")
    manifest, _, pattern, raw_contract = _dataset_context(project_root, source_id, dataset_id)
    validate_execution_model(pattern, execution_model)
    dataset_root = project_root / "silver_processing" / source_id / dataset_id
    pipeline_file = dataset_root / "pipeline.yml"
    if not pipeline_file.is_file():
        raise FileNotFoundError(
            f"initial dataset pipeline must exist before creating a version: {pipeline_file}"
        )
    destination = dataset_root / "versions" / version
    if destination.exists():
        return ScaffoldVersionResult(
            source_id=source_id,
            dataset_id=dataset_id,
            version=version,
            destination=destination,
            created=False,
        )

    rendered = render_implementation_files(
        project_root=project_root,
        source_id=source_id,
        dataset_id=dataset_id,
        pattern=pattern,
        raw_contract=raw_contract,
        version=version,
        owner=str(manifest["source"]["owner"]),
        candidate=True,
        include_pipeline=False,
        template_root=template_root,
        execution_model=execution_model,
        target_lag=target_lag,
        warehouse=warehouse,
        refresh_mode=refresh_mode,
    )
    destination.mkdir(parents=True, exist_ok=False)
    for filename, text in rendered.items():
        (destination / filename).write_text(text, encoding="utf-8")
    return ScaffoldVersionResult(
        source_id=source_id,
        dataset_id=dataset_id,
        version=version,
        destination=destination,
        created=True,
    )


def existing_versions(project_root: Path, source_id: str, dataset_id: str) -> tuple[str, ...]:
    root = project_root.resolve() / "silver_processing" / source_id / dataset_id
    versions = {"v1"} if root.is_dir() else set()
    version_root = root / "versions"
    if version_root.is_dir():
        for path in version_root.iterdir():
            if path.is_dir() and VERSION_RE.fullmatch(path.name):
                versions.add(path.name)
    return tuple(sorted(versions, key=validate_version))


def next_version(project_root: Path, source_id: str, dataset_id: str) -> str:
    versions = existing_versions(project_root, source_id, dataset_id)
    if not versions:
        return "v1"
    return f"v{max(validate_version(version) for version in versions) + 1}"


def _require_version_implementation(
    project_root: Path, source_id: str, dataset_id: str, version: str
) -> None:
    validate_version(version)
    dataset_root = project_root / "silver_processing" / source_id / dataset_id
    if version == "v1":
        required = dataset_root / "version.yml"
    else:
        required = dataset_root / "versions" / version / "version.yml"
    if not required.is_file():
        raise FileNotFoundError(f"version implementation not found: {required}")


def generate_release_scripts(
    *,
    project_root: Path,
    source_id: str,
    dataset_id: str,
    from_version: str,
    to_version: str,
    output_root: Path | None = None,
) -> ReleaseScriptsResult:
    project_root = project_root.resolve()
    validate_version(from_version)
    validate_version(to_version)
    if from_version == to_version:
        raise ValueError("from_version and to_version must differ")
    _require_version_implementation(project_root, source_id, dataset_id, from_version)
    _require_version_implementation(project_root, source_id, dataset_id, to_version)
    _, _, pattern, raw_contract = _dataset_context(project_root, source_id, dataset_id)
    contract = _load_raw_contract(project_root, raw_contract, source_id)
    from_execution = load_version_execution(
        project_root, source_id, dataset_id, from_version, pattern=pattern
    )
    to_execution = load_version_execution(
        project_root, source_id, dataset_id, to_version, pattern=pattern
    )
    names_from = build_names(
        source_id=source_id,
        dataset_id=dataset_id,
        pattern=pattern,
        entity=str(contract["entity"]),
        version=from_version,
        execution_model=from_execution.execution_model,
    )
    names_to = build_names(
        source_id=source_id,
        dataset_id=dataset_id,
        pattern=pattern,
        entity=str(contract["entity"]),
        version=to_version,
        execution_model=to_execution.execution_model,
    )
    activate, rollback = render_release_sql(pattern, names_from, names_to)
    root = (output_root or project_root / "operations" / "release").resolve()
    destination = root / source_id / dataset_id / f"{from_version}_to_{to_version}"
    if destination.exists():
        return ReleaseScriptsResult(
            source_id=source_id,
            dataset_id=dataset_id,
            from_version=from_version,
            to_version=to_version,
            destination=destination,
            created=False,
            files=(),
        )
    destination.mkdir(parents=True, exist_ok=False)
    readme = (
        f"# Release {source_id}.{dataset_id}: {from_version} -> {to_version}\n\n"
        "These scripts are generated for review and explicit execution. They are never run by `esf`.\n\n"
        f"From execution model: `{from_execution.execution_model}`  \n"
        f"To execution model: `{to_execution.execution_model}`\n\n"
        "1. Deploy the candidate version.\n"
        "2. Bootstrap/replay or refresh historical Bronze evidence as appropriate for its execution model.\n"
        "3. Run candidate validation and active-vs-candidate comparison.\n"
        "4. Review and run `activate.sql`.\n"
        "5. Keep `rollback.sql` for the approved rollback window.\n"
    )
    files = {
        "README.md": readme,
        "activate.sql": activate,
        "rollback.sql": rollback,
    }
    paths: list[Path] = []
    for filename, text in files.items():
        path = destination / filename
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return ReleaseScriptsResult(
        source_id=source_id,
        dataset_id=dataset_id,
        from_version=from_version,
        to_version=to_version,
        destination=destination,
        created=True,
        files=tuple(paths),
    )
