from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dataset_management import DATASET_ID_PATTERN
from .source_management import SOURCE_ID_PATTERN, source_manifest_path
from .validation import default_schema_dir, load_document, load_schema, schema_errors, validate_raw_contract


@dataclass(frozen=True)
class RawContractDraftResult:
    source_id: str
    dataset_id: str
    destination: Path
    created: bool
    reason: str | None = None


@dataclass(frozen=True)
class FinalizeRawContractResult:
    source_id: str
    dataset_id: str
    draft: Path
    destination: Path
    created: bool
    reason: str | None = None


def raw_contract_draft_path(project_root: Path, source_id: str, dataset_id: str) -> Path:
    return project_root.resolve() / "contracts" / "drafts" / source_id / f"{dataset_id}.yml"


def raw_contract_path(project_root: Path, source_id: str, dataset_id: str) -> Path:
    return project_root.resolve() / "contracts" / "raw" / source_id / f"{dataset_id}.yml"


def _validate_ids(source_id: str, dataset_id: str) -> None:
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise ValueError("source id must match ^[a-z][a-z0-9_]{1,63}$")
    if not DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise ValueError("dataset id must match ^[a-z][a-z0-9_]{1,63}$")


def _ensure_source(project_root: Path, source_id: str) -> None:
    manifest = source_manifest_path(project_root, source_id)
    if not manifest.is_file():
        raise FileNotFoundError(f"source manifest not found: {manifest}")


def _draft_text(source_id: str, dataset_id: str) -> str:
    return f"""# RAW CONTRACT DRAFT ONLY.
# This file is intentionally outside contracts/raw/ and is ignored by `esf validate`.
# Replace/remove every TODO value using source evidence and engineering judgement.
# The Framework does not infer business keys, ordering, CDC semantics, or SCD pattern.

schema_version: 2

contract:
  source_system: {source_id}
  entity: {dataset_id}

  # Describe what one landed Bronze row represents.
  grain: "TODO: describe the row grain"

  # Choose the durable business identity. Do not assume the source PK is correct.
  business_key:
    - TODO_BUSINESS_KEY

  # Remove this field when the source has no trustworthy event/change timestamp.
  source_timestamp: TODO_SOURCE_TIMESTAMP

  # Replace this starter list with the actual landed Bronze columns and Snowflake types.
  columns:
    - name: TODO_BUSINESS_KEY
      type: TODO_SNOWFLAKE_TYPE
      nullable: false
    - name: TODO_SOURCE_TIMESTAMP
      type: TIMESTAMP_NTZ
      nullable: false
    - name: INGESTED_AT
      type: TIMESTAMP_LTZ
      nullable: false

  change_semantics:
    # Required decision: snapshot | append | cdc
    mode: TODO_CHANGE_MODE

    # Optional/conditional fields. Remove fields that do not apply.
    # operation_column: SOURCE_OPERATION
    # sequence_column: SOURCE_SEQUENCE
    delete_semantics: TODO_DELETE_SEMANTICS
    # delete_values: [D]

  # Required decision: current_state | net_change | full_change | full_event
  capture_fidelity: TODO_CAPTURE_FIDELITY

  # Keep only when deterministic source ordering exists; otherwise remove the block.
  ordering_columns:
    - TODO_ORDERING_COLUMN

  # Identify one landed source event/row so replay can be idempotent.
  idempotency_key:
    - TODO_IDEMPOTENCY_COLUMN

  # Required decision: reject | versioned_contract | approved_migration
  breaking_change_policy: TODO_BREAKING_CHANGE_POLICY
"""


def create_raw_contract_draft(
    project_root: Path,
    source_id: str,
    dataset_id: str,
) -> RawContractDraftResult:
    project_root = project_root.resolve()
    _validate_ids(source_id, dataset_id)
    _ensure_source(project_root, source_id)

    draft = raw_contract_draft_path(project_root, source_id, dataset_id)
    final = raw_contract_path(project_root, source_id, dataset_id)

    if final.exists():
        return RawContractDraftResult(
            source_id=source_id,
            dataset_id=dataset_id,
            destination=draft,
            created=False,
            reason=f"formal RAW contract already exists: {final}",
        )
    if draft.exists():
        return RawContractDraftResult(
            source_id=source_id,
            dataset_id=dataset_id,
            destination=draft,
            created=False,
            reason="draft already exists",
        )

    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(_draft_text(source_id, dataset_id), encoding="utf-8")
    return RawContractDraftResult(
        source_id=source_id,
        dataset_id=dataset_id,
        destination=draft,
        created=True,
    )


def _placeholder_paths(value: Any, path: str = "<root>") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_placeholder_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_placeholder_paths(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        upper = value.upper()
        if "TODO_" in upper or upper.startswith("TODO:") or "REPLACE_ME" in upper:
            found.append(path)
    return found


def _validation_errors(document: dict[str, Any], path: Path) -> list[str]:
    schema = load_schema(default_schema_dir(), "raw_contract")
    errors = schema_errors(document, schema, path)
    if not errors:
        errors.extend(validate_raw_contract(document, path))
    return errors


def finalize_raw_contract(
    project_root: Path,
    source_id: str,
    dataset_id: str,
) -> FinalizeRawContractResult:
    project_root = project_root.resolve()
    _validate_ids(source_id, dataset_id)
    _ensure_source(project_root, source_id)

    draft = raw_contract_draft_path(project_root, source_id, dataset_id)
    final = raw_contract_path(project_root, source_id, dataset_id)

    if final.exists():
        return FinalizeRawContractResult(
            source_id=source_id,
            dataset_id=dataset_id,
            draft=draft,
            destination=final,
            created=False,
            reason="formal RAW contract already exists",
        )
    if not draft.is_file():
        raise FileNotFoundError(f"RAW contract draft not found: {draft}")

    document = load_document(draft)
    placeholders = _placeholder_paths(document)
    if placeholders:
        raise ValueError(
            "RAW contract draft still contains unresolved TODO values at: "
            + ", ".join(placeholders)
        )

    errors = _validation_errors(document, draft)
    if errors:
        raise ValueError("RAW contract draft is invalid:\n- " + "\n- ".join(errors))

    contract = document.get("contract")
    if not isinstance(contract, dict):
        raise ValueError(f"invalid RAW contract draft: {draft}")
    if contract.get("source_system") != source_id:
        raise ValueError(
            f"RAW contract source_system must match source {source_id}: "
            f"{contract.get('source_system')}"
        )

    # Preserve the engineer-reviewed bytes exactly. Finalization is an explicit promotion
    # from the ignored drafts area into the validated contracts/raw boundary.
    final.parent.mkdir(parents=True, exist_ok=True)
    draft.replace(final)

    return FinalizeRawContractResult(
        source_id=source_id,
        dataset_id=dataset_id,
        draft=draft,
        destination=final,
        created=True,
    )
