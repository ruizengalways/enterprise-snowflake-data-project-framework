from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .execution_model import default_execution_model, load_version_execution, validate_execution_model
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
    execution_model: str | None = None,
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
    model = execution_model or default_execution_model(pattern)
    validate_execution_model(pattern, model)
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
        execution_model=model,
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


def _release_preflight_sql(dataset_key: str, from_version: str, to_version: str) -> str:
    return f"""-- Read-only release preview. activate.sql repeats these checks as hard guards immediately before cutover.
-- READY may proceed after engineer review. REVIEW_REQUIRED needs explicit acceptance when generating activate.sql.
-- BLOCKED must not be bypassed.
SELECT
    DATASET_ID,
    ACTIVE_VERSION,
    CANDIDATE_VERSION,
    INVARIANT_STATUS,
    INVARIANT_REASON,
    CANDIDATE_VERSION_STATUS,
    CANDIDATE_EXECUTION_MODEL,
    RUNTIME_STATUS,
    RUNTIME_EVIDENCE_AT,
    DQ_STATUS,
    DQ_CHECKED_AT,
    COMPARISON_STATUS,
    COMPARISON_VALIDATED_AT,
    READINESS_STATUS,
    READINESS_REASON
FROM CONTROL.RELEASE_READINESS_V
WHERE DATASET_ID = '{dataset_key}';

-- The requested edge must match the environment state; the generated activate.sql fails closed otherwise.
SELECT
    DATASET_ID,
    ACTIVE_VERSION,
    CANDIDATE_VERSION,
    IFF(ACTIVE_VERSION = '{from_version}' AND CANDIDATE_VERSION = '{to_version}', 'PASS', 'BLOCKED') AS REQUESTED_EDGE_STATUS
FROM CONTROL.DATASET
WHERE DATASET_ID = '{dataset_key}';
"""


def _release_postflight_sql(dataset_key: str) -> str:
    return f"""-- Read-only release/rollback verification aid. The operation scripts also run hard postflight checks.
SELECT *
FROM CONTROL.RELEASE_RUN_LATEST_V
WHERE DATASET_ID = '{dataset_key}';

SELECT *
FROM CONTROL.DATASET_VERSION_INVARIANT_V
WHERE DATASET_ID = '{dataset_key}';

SELECT
    DATASET_ID,
    VERSION,
    STATUS,
    EXECUTION_MODEL,
    PRIMARY_RUNTIME_OBJECT,
    DEPLOYED_AT,
    ACTIVATED_AT,
    RETIRED_AT,
    UPDATED_AT
FROM CONTROL.DATASET_VERSION
WHERE DATASET_ID = '{dataset_key}'
ORDER BY VERSION;
"""


def generate_release_scripts(
    *,
    project_root: Path,
    source_id: str,
    dataset_id: str,
    from_version: str,
    to_version: str,
    output_root: Path | None = None,
    allow_review_required: bool = False,
    operator_reason: str | None = None,
) -> ReleaseScriptsResult:
    project_root = project_root.resolve()
    validate_version(from_version)
    validate_version(to_version)
    if from_version == to_version:
        raise ValueError("from_version and to_version must differ")
    if allow_review_required and not operator_reason:
        raise ValueError("operator_reason is required when allowing REVIEW_REQUIRED release evidence")
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
    activate, rollback = render_release_sql(
        pattern,
        names_from,
        names_to,
        allow_review_required=allow_review_required,
        operator_reason=operator_reason,
    )
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
    acceptance = (
        "This bundle was generated with explicit acceptance of REVIEW_REQUIRED evidence. "
        f"Recorded reason: `{operator_reason}`\n\n"
        if allow_review_required
        else "`REVIEW_REQUIRED` blocks activation by default. Regenerate with `--allow-review-required --reason ...` only after reviewing the evidence.\n\n"
    )
    readme = (
        f"# Release {source_id}.{dataset_id}: {from_version} -> {to_version}\n\n"
        "These scripts are generated for review and explicit execution. They are never run by `esf`.\n\n"
        "Control migration `120_release_readiness.sql` must be applied before this bundle is executed.\n\n"
        f"From execution model: `{from_execution.execution_model}`  \n"
        f"To execution model: `{to_execution.execution_model}`\n\n"
        "`CONTROL.RELEASE_READINESS_V` consumes existing candidate runtime, DQ, comparison and version-pointer evidence. "
        "It does not approve a candidate or infer business correctness.\n\n"
        + acceptance
        + "Recommended flow:\n\n"
        "1. Deploy the candidate version.\n"
        "2. Bootstrap/replay or refresh historical Bronze evidence as appropriate for its execution model.\n"
        "3. Run candidate validation and active-vs-candidate comparison after the latest candidate runtime update.\n"
        "4. Run `preflight.sql` and review `READY`, `REVIEW_REQUIRED` or `BLOCKED`.\n"
        "5. Review and run `activate.sql`; it repeats preflight as a hard guard and writes `CONTROL.RELEASE_RUN`.\n"
        "6. Run `postflight.sql` and keep `rollback.sql` for the approved rollback window.\n\n"
        "Rollback is intentionally blocked if another candidate has been registered since cutover. "
        "Do not use an old rollback bundle after a newer release cycle has begun.\n"
    )
    files = {
        "README.md": readme,
        "preflight.sql": _release_preflight_sql(names_to.dataset_key, from_version, to_version),
        "activate.sql": activate,
        "rollback.sql": rollback,
        "postflight.sql": _release_postflight_sql(names_to.dataset_key),
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
