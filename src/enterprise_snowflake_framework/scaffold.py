from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .pipeline_sql import (
    build_names,
    render_apply_sql,
    render_compare_sql,
    render_deploy_fragment,
    render_objects_sql,
    render_policy_sql,
    render_publish_sql,
    render_register_sql,
    render_replay_sql,
    render_task_sql,
    render_validate_sql,
    render_version_yaml,
)
from .plan import STANDARD_DATASET_FILES, SourcePlan, build_source_plan
from .source_management import load_source_manifest

SUPPORTED_PATTERNS = {"append", "full_refresh", "scd1", "scd2", "custom"}


@dataclass(frozen=True)
class ScaffoldDatasetResult:
    source_id: str
    dataset_id: str
    pattern: str
    destination: Path
    created: bool
    missing_standard_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScaffoldAllResult:
    source_id: str
    created: tuple[ScaffoldDatasetResult, ...]
    skipped: tuple[ScaffoldDatasetResult, ...]

    @property
    def overwritten(self) -> int:
        return 0


@dataclass(frozen=True)
class ScaffoldPreviewResult:
    source_id: str
    dataset_id: str
    pattern: str
    destination: Path
    domain_owned: bool
    files: tuple[str, ...]
    rendered: dict[str, str]


def _repo_template_root() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _load_raw_contract(project_root: Path, raw_contract: str, source_id: str) -> dict[str, Any]:
    project_root = project_root.resolve()
    contract_path = (project_root / raw_contract).resolve()
    try:
        contract_path.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"RAW contract path escapes project root: {raw_contract}") from exc
    expected_root = (project_root / "contracts" / "raw" / source_id).resolve()
    try:
        contract_path.relative_to(expected_root)
    except ValueError as exc:
        raise ValueError(f"RAW contract for {source_id} must be under contracts/raw/{source_id}/") from exc
    if not contract_path.is_file():
        raise FileNotFoundError(f"RAW contract not found: {raw_contract}")
    document = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("contract"), dict):
        raise ValueError(f"invalid RAW contract document: {raw_contract}")
    contract = document["contract"]
    if contract.get("source_system") != source_id:
        raise ValueError(
            f"RAW contract source_system must match source {source_id}: {contract.get('source_system')}"
        )
    return contract


def _project_code(project_root: Path) -> str:
    path = project_root.resolve() / "config" / "project.yml"
    if not path.is_file():
        raise FileNotFoundError(f"project metadata not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        code = str(document["project"]["code"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid project metadata: {path}") from exc
    return code.upper()


def _tracked_columns(contract: dict[str, Any]) -> list[str]:
    changes = contract.get("change_semantics", {})
    excluded = {str(value) for value in contract.get("business_key", [])}
    excluded.update(str(value) for value in contract.get("ordering_columns", []))
    excluded.update(str(value) for value in contract.get("idempotency_key", []))
    excluded.add("ingested_at")
    if contract.get("source_timestamp"):
        excluded.add(str(contract["source_timestamp"]))
    for key in ("operation_column", "sequence_column"):
        if changes.get(key):
            excluded.add(str(changes[key]))
    return [
        str(column["name"])
        for column in contract.get("columns", [])
        if isinstance(column, dict) and str(column.get("name")) not in excluded
    ]


def _pipeline_yaml(
    pattern: str, source_id: str, dataset_id: str, raw_contract: str, contract: dict[str, Any]
) -> str:
    names = build_names(
        source_id=source_id,
        dataset_id=dataset_id,
        pattern=pattern,
        entity=str(contract["entity"]),
        version="v1",
    )
    lines = [
        "schema_version: 1",
        "",
        "pipeline:",
        f"  id: {dataset_id}",
        f"  pattern: {pattern}",
        f"  raw_contract: {raw_contract}",
        "",
        "  input:",
        f"    relation: {names.bronze_relation}",
        "",
        "  output:",
    ]
    if pattern == "scd2":
        lines.extend(
            [
                f"    history: {names.published_history}",
                f"    current: {names.published_current}",
            ]
        )
        tracked = _tracked_columns(contract)
        if not tracked:
            raise ValueError("scd2 scaffold requires at least one tracked payload column")
        lines.extend(["", "  tracked_columns:"])
        lines.extend(f"    - {item}" for item in tracked)
    elif pattern == "scd1":
        lines.append(f"    current: {names.published_relation}")
    else:
        relation = names.published_relation or f"SILVER.{names.object_base}"
        lines.append(f"    relation: {relation}")
    return "\n".join(lines) + "\n"


def _render_readme(
    *, pattern: str, dataset_id: str, source_id: str, version: str, candidate: bool,
    template_root: Path | None,
) -> str:
    root = (template_root or _repo_template_root()).resolve()
    path = root / pattern / "README.md"
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        text = text.replace("__DATASET_ID__", dataset_id).replace("__SOURCE_ID__", source_id)
    else:
        text = f"# {dataset_id} — {pattern}\n"
    suffix = (
        f"\n## Implementation version\n\n`{version}` is a {'candidate' if candidate else 'initial'} "
        "implementation. SQL in this directory is domain-owned after creation.\n"
    )
    return text.rstrip() + "\n" + suffix


def render_implementation_files(
    *, project_root: Path, source_id: str, dataset_id: str, pattern: str,
    raw_contract: str, version: str, owner: str, candidate: bool,
    include_pipeline: bool, template_root: Path | None = None,
) -> dict[str, str]:
    if pattern not in SUPPORTED_PATTERNS:
        raise ValueError(f"unsupported scaffold pattern: {pattern}")
    contract = _load_raw_contract(project_root, raw_contract, source_id)
    names = build_names(
        source_id=source_id,
        dataset_id=dataset_id,
        pattern=pattern,
        entity=str(contract["entity"]),
        version=version,
    )
    rendered = {
        "README.md": _render_readme(
            pattern=pattern, dataset_id=dataset_id, source_id=source_id,
            version=version, candidate=candidate, template_root=template_root,
        ),
        "version.yml": render_version_yaml(names, candidate=candidate),
        "001_objects.sql": render_objects_sql(pattern, names, contract),
        "010_apply.sql": render_apply_sql(pattern, names, contract),
        "015_replay.sql": render_replay_sql(pattern, names, contract),
        "020_validate.sql": render_validate_sql(pattern, names, contract),
        "025_compare.sql": render_compare_sql(pattern, names, contract, candidate=candidate),
        "030_task.sql": render_task_sql(pattern, names, _project_code(project_root)),
        "040_register.sql": render_register_sql(pattern, names, owner=owner, candidate=candidate),
        "050_publish.sql": render_publish_sql(pattern, names, candidate=candidate),
        "060_policy.sql": render_policy_sql(names, candidate=candidate),
        "deploy_manifest.fragment.txt": render_deploy_fragment(names, candidate=candidate),
    }
    if include_pipeline:
        rendered["pipeline.yml"] = _pipeline_yaml(pattern, source_id, dataset_id, raw_contract, contract)
    return rendered


def _dataset_config(project_root: Path, source_id: str, dataset_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = load_source_manifest(project_root, source_id)
    config = manifest["datasets"].get(dataset_id)
    if not isinstance(config, dict):
        raise KeyError(f"dataset is not declared in source manifest: {source_id}.{dataset_id}")
    return manifest, config


def _prepare_dataset(
    *, project_root: Path, source_id: str, pattern: str, dataset_id: str,
    raw_contract: str, owner: str, template_root: Path | None = None,
) -> tuple[Path, dict[str, str]]:
    project_root = project_root.resolve()
    destination = project_root / "silver_processing" / source_id / dataset_id
    if destination.exists():
        raise FileExistsError(f"domain-owned dataset directory already exists: {destination}")
    rendered = render_implementation_files(
        project_root=project_root, source_id=source_id, dataset_id=dataset_id,
        pattern=pattern, raw_contract=raw_contract, version="v1", owner=owner,
        candidate=False, include_pipeline=True, template_root=template_root,
    )
    return destination, rendered


def _write_prepared(destination: Path, rendered: dict[str, str]) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for filename, text in rendered.items():
        (destination / filename).write_text(text, encoding="utf-8")


def scaffold_preview(
    *, project_root: Path, source_id: str, dataset_id: str, template_root: Path | None = None
) -> ScaffoldPreviewResult:
    project_root = project_root.resolve()
    manifest, config = _dataset_config(project_root, source_id, dataset_id)
    pattern = str(config.get("pattern"))
    raw_contract = config.get("raw_contract")
    if not isinstance(raw_contract, str):
        raise ValueError(f"raw_contract is required for {source_id}.{dataset_id}")
    destination = project_root / "silver_processing" / source_id / dataset_id
    if destination.exists():
        return ScaffoldPreviewResult(
            source_id=source_id, dataset_id=dataset_id, pattern=pattern,
            destination=destination, domain_owned=True, files=(), rendered={},
        )
    rendered = render_implementation_files(
        project_root=project_root, source_id=source_id, dataset_id=dataset_id,
        pattern=pattern, raw_contract=raw_contract, version="v1",
        owner=str(manifest["source"]["owner"]), candidate=False,
        include_pipeline=True, template_root=template_root,
    )
    return ScaffoldPreviewResult(
        source_id=source_id, dataset_id=dataset_id, pattern=pattern,
        destination=destination, domain_owned=False,
        files=tuple(sorted(rendered)), rendered=rendered,
    )


def scaffold_pipeline(
    *, project_root: Path, source_id: str, pattern: str, dataset_id: str,
    template_root: Path | None = None,
) -> ScaffoldDatasetResult:
    project_root = project_root.resolve()
    manifest, config = _dataset_config(project_root, source_id, dataset_id)
    manifest_pattern = config.get("pattern")
    if pattern != manifest_pattern:
        raise ValueError(
            f"scaffold pattern must match source manifest for {source_id}.{dataset_id}: "
            f"requested={pattern}, manifest={manifest_pattern}"
        )
    raw_contract = config.get("raw_contract")
    if not isinstance(raw_contract, str):
        raise ValueError(f"raw_contract is required for {source_id}.{dataset_id}")
    destination = project_root / "silver_processing" / source_id / dataset_id
    if destination.exists():
        missing = tuple(name for name in STANDARD_DATASET_FILES if not (destination / name).is_file())
        return ScaffoldDatasetResult(
            source_id=source_id, dataset_id=dataset_id, pattern=pattern,
            destination=destination, created=False, missing_standard_files=missing,
        )
    destination, rendered = _prepare_dataset(
        project_root=project_root, source_id=source_id, pattern=pattern,
        dataset_id=dataset_id, raw_contract=raw_contract,
        owner=str(manifest["source"]["owner"]), template_root=template_root,
    )
    _write_prepared(destination, rendered)
    return ScaffoldDatasetResult(
        source_id=source_id, dataset_id=dataset_id, pattern=pattern,
        destination=destination, created=True,
    )


def scaffold_all(
    *, project_root: Path, source_id: str, template_root: Path | None = None
) -> ScaffoldAllResult:
    project_root = project_root.resolve()
    plan: SourcePlan = build_source_plan(project_root, source_id)
    manifest = load_source_manifest(project_root, source_id)
    prepared: list[tuple[str, str, Path, dict[str, str]]] = []
    for item in plan.new:
        config = manifest["datasets"][item.dataset_id]
        raw_contract = config.get("raw_contract")
        if not isinstance(raw_contract, str):
            raise ValueError(f"raw_contract is required for {source_id}.{item.dataset_id}")
        destination, rendered = _prepare_dataset(
            project_root=project_root, source_id=source_id, pattern=item.pattern,
            dataset_id=item.dataset_id, raw_contract=raw_contract,
            owner=str(manifest["source"]["owner"]), template_root=template_root,
        )
        prepared.append((item.dataset_id, item.pattern, destination, rendered))
    created: list[ScaffoldDatasetResult] = []
    for dataset_id, pattern, destination, rendered in prepared:
        _write_prepared(destination, rendered)
        created.append(ScaffoldDatasetResult(
            source_id=source_id, dataset_id=dataset_id, pattern=pattern,
            destination=destination, created=True,
        ))
    skipped = tuple(
        ScaffoldDatasetResult(
            source_id=source_id, dataset_id=item.dataset_id, pattern=item.pattern,
            destination=item.directory, created=False,
            missing_standard_files=item.missing_standard_files,
        )
        for item in plan.existing
    )
    return ScaffoldAllResult(source_id=source_id, created=tuple(created), skipped=skipped)
