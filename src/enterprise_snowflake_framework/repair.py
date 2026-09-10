from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .pipeline_model import column_names
from .pipeline_sql import build_names
from .scaffold import _load_raw_contract
from .source_management import load_source_manifest
from .versioning import next_version, validate_version

PROBLEM_LAYERS = {"ingestion", "silver", "gold"}
STANDARD_REPAIR_PATTERNS = {"append", "full_refresh", "scd1", "scd2"}


@dataclass(frozen=True)
class RepairPlan:
    source_id: str
    dataset_id: str
    problem: str
    known_good_layer: str
    recommended_action: str
    recommended_candidate: str | None
    requested_from: str | None
    requested_to: str | None
    active_production_overwrite: bool
    notes: tuple[str, ...]

    def render(self) -> str:
        lines = [
            f"REPAIR PLAN: {self.source_id}.{self.dataset_id}",
            "",
            f"Problem layer: {self.problem.upper()}",
            f"Known-good layer: {self.known_good_layer}",
            f"Recommended action: {self.recommended_action}",
        ]
        if self.recommended_candidate:
            lines.append(f"Recommended candidate: {self.recommended_candidate}")
        if self.requested_from or self.requested_to:
            lines.append(
                f"Requested range: {self.requested_from or '<start>'} -> {self.requested_to or '<current>'}"
            )
        lines.extend(
            [
                "",
                f"Will overwrite active production: {'YES' if self.active_production_overwrite else 'NO'}",
                "",
                "Next checks:",
            ]
        )
        lines.extend(f"  - {note}" for note in self.notes)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class RepairScriptsResult:
    source_id: str
    dataset_id: str
    candidate_version: str
    destination: Path
    created: bool
    files: tuple[Path, ...]


def _dataset_config(project_root: Path, source_id: str, dataset_id: str) -> dict:
    manifest = load_source_manifest(project_root, source_id)
    config = manifest["datasets"].get(dataset_id)
    if not isinstance(config, dict):
        raise KeyError(f"dataset is not declared in source manifest: {source_id}.{dataset_id}")
    return config


def build_repair_plan(
    *,
    project_root: Path,
    source_id: str,
    dataset_id: str,
    problem: str,
    requested_from: str | None = None,
    requested_to: str | None = None,
) -> RepairPlan:
    project_root = project_root.resolve()
    if problem not in PROBLEM_LAYERS:
        raise ValueError(f"problem must be one of: {', '.join(sorted(PROBLEM_LAYERS))}")
    config = _dataset_config(project_root, source_id, dataset_id)
    pattern = str(config.get("pattern"))

    if problem == "ingestion":
        return RepairPlan(
            source_id=source_id,
            dataset_id=dataset_id,
            problem=problem,
            known_good_layer="SOURCE / connector-specific evidence",
            recommended_action="repair Source -> Bronze with the owning ingestion technology, then replay downstream",
            recommended_candidate=None,
            requested_from=requested_from,
            requested_to=requested_to,
            active_production_overwrite=False,
            notes=(
                "Confirm Bronze is complete before touching Silver.",
                "Use Openflow/Snowpipe/Kafka/API/Talend/ADF recovery in the system that owns ingestion.",
                "After Bronze is correct, plan a Silver replay for the affected range.",
                "Rebuild only affected dbt descendants after Silver is healthy.",
            ),
        )

    if problem == "gold":
        return RepairPlan(
            source_id=source_id,
            dataset_id=dataset_id,
            problem=problem,
            known_good_layer="SILVER",
            recommended_action="fix dbt code and rebuild the affected model graph from trusted Silver",
            recommended_candidate=None,
            requested_from=requested_from,
            requested_to=requested_to,
            active_production_overwrite=False,
            notes=(
                "Do not rerun ingestion without evidence Bronze is wrong.",
                "Do not replay Silver without evidence Silver is wrong.",
                "Use dbt selection to rebuild the smallest affected descendant graph.",
                "Close the incident only after health/DQ/SLA checks recover.",
            ),
        )

    candidate = next_version(project_root, source_id, dataset_id)
    notes = [
        "Confirm Bronze retains the evidence needed for replay.",
        f"Create candidate {candidate} and keep the current active version serving production.",
        "For a new empty candidate, prefer a full bootstrap with no --from/--to bounds.",
        "Use a bounded replay only when the candidate already has a correct baseline outside the requested range.",
        "Catch up the candidate, then run shadow validation and active-vs-candidate reconciliation.",
        "Generate explicit release SQL only after validation passes.",
        "Rebuild affected dbt descendants after activation.",
    ]
    if pattern == "full_refresh":
        notes[2] = "Full-refresh repair rebuilds the candidate from the current complete Bronze snapshot; time-range replay is not meaningful."
        notes.pop(3)
    elif pattern == "custom":
        notes[2] = "CUSTOM repair remains domain-authored; document replay evidence and invariants before writing recovery SQL."
        notes.pop(3)
    return RepairPlan(
        source_id=source_id,
        dataset_id=dataset_id,
        problem=problem,
        known_good_layer="BRONZE",
        recommended_action="build a new Silver candidate version and replay from Bronze",
        recommended_candidate=candidate,
        requested_from=requested_from,
        requested_to=requested_to,
        active_production_overwrite=False,
        notes=tuple(notes),
    )


def _sql_timestamp(value: str | None) -> str:
    if value is None:
        return "NULL"
    escaped = value.replace("'", "''")
    return f"TO_TIMESTAMP_NTZ('{escaped}')"


def _has_replay_timestamp(contract: dict) -> bool:
    return bool(contract.get("source_timestamp")) or "INGESTED_AT" in column_names(contract)


def _validate_bounded_replay(pattern: str, contract: dict, requested_from: str | None, requested_to: str | None) -> None:
    bounded = requested_from is not None or requested_to is not None
    if not bounded:
        return
    if pattern == "full_refresh":
        raise ValueError("full_refresh repair rebuilds the current Bronze snapshot and does not accept --from/--to")
    if pattern in {"append", "scd1"} and not _has_replay_timestamp(contract):
        raise ValueError(
            f"{pattern} ranged repair requires RAW source_timestamp or INGESTED_AT; use a full bootstrap instead"
        )
    if pattern == "scd1":
        delete_semantics = str(contract.get("change_semantics", {}).get("delete_semantics", "none"))
        if delete_semantics not in {"none", "tombstone"}:
            raise ValueError(
                "bounded scd1 repair requires delete_semantics none/tombstone so deleted keys remain discoverable; use a full bootstrap instead"
            )


def generate_silver_repair_scripts(
    *,
    project_root: Path,
    source_id: str,
    dataset_id: str,
    candidate_version: str,
    requested_from: str | None = None,
    requested_to: str | None = None,
    output_root: Path | None = None,
) -> RepairScriptsResult:
    project_root = project_root.resolve()
    number = validate_version(candidate_version)
    if number < 2:
        raise ValueError("repair SQL must target a candidate version v2 or later")
    config = _dataset_config(project_root, source_id, dataset_id)
    pattern = str(config.get("pattern"))
    if pattern == "custom":
        raise ValueError("CUSTOM repair remains domain-authored; repair-sql only supports standard patterns")
    if pattern not in STANDARD_REPAIR_PATTERNS:
        raise ValueError(f"unsupported repair pattern: {pattern}")

    raw_contract = config.get("raw_contract")
    if not isinstance(raw_contract, str):
        raise ValueError(f"raw_contract is required for {source_id}.{dataset_id}")
    contract = _load_raw_contract(project_root, raw_contract, source_id)
    _validate_bounded_replay(pattern, contract, requested_from, requested_to)

    implementation = (
        project_root
        / "silver_processing"
        / source_id
        / dataset_id
        / "versions"
        / candidate_version
        / "version.yml"
    )
    if not implementation.is_file():
        raise FileNotFoundError(
            f"candidate implementation not found; run scaffold-version first: {implementation}"
        )
    names = build_names(
        source_id=source_id,
        dataset_id=dataset_id,
        pattern=pattern,
        entity=str(contract["entity"]),
        version=candidate_version,
    )
    root = (output_root or project_root / "operations" / "replay").resolve()
    destination = root / source_id / dataset_id / candidate_version
    if destination.exists():
        return RepairScriptsResult(
            source_id=source_id,
            dataset_id=dataset_id,
            candidate_version=candidate_version,
            destination=destination,
            created=False,
            files=(),
        )
    destination.mkdir(parents=True, exist_ok=False)

    if pattern == "full_refresh":
        replay_call = f"CALL {names.replay_procedure}();"
        range_note = "This pattern rebuilds from the current complete Bronze snapshot; no time range is applied."
    else:
        replay_call = f"""CALL {names.replay_procedure}(
    {_sql_timestamp(requested_from)},
    {_sql_timestamp(requested_to)}
);"""
        range_note = (
            "No bounds were supplied: this is a full candidate bootstrap from retained Bronze evidence."
            if requested_from is None and requested_to is None
            else "A bounded replay assumes this candidate already has a correct baseline outside the requested range."
        )

    sql = f"""-- Engineer-reviewed Silver repair for pattern {pattern}. `esf` never executes this file.
-- Active production remains untouched; this rebuilds candidate {candidate_version} only.
-- {range_note}

ALTER TASK {names.task} SUSPEND;

{replay_call}

-- Review candidate validation before catch-up/activation:
-- silver_processing/{source_id}/{dataset_id}/versions/{candidate_version}/020_validate.sql
-- Then catch up new changes with CALL {names.apply_procedure}(); or resume its task when configured.
-- Generate activate/rollback SQL separately with `esf release-sql` only after validation.
"""
    readme = f"""# Silver repair: {source_id}.{dataset_id} {candidate_version}

Pattern: `{pattern}`

This directory is generated for review, not automatic execution.

1. Confirm Bronze is the known-good layer and retains the evidence required by this pattern.
2. Deploy the candidate implementation.
3. Review and run `repair.sql` against the candidate only.
4. Run candidate validation and active-vs-candidate reconciliation.
5. Catch up new events or the next snapshot as appropriate.
6. Generate release SQL only when the candidate is approved.

{range_note}
"""
    files = {"README.md": readme, "repair.sql": sql}
    paths: list[Path] = []
    for filename, text in files.items():
        path = destination / filename
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return RepairScriptsResult(
        source_id=source_id,
        dataset_id=dataset_id,
        candidate_version=candidate_version,
        destination=destination,
        created=True,
        files=tuple(paths),
    )
