import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.metadata_validation import validate_project_tree


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "project_schema"


def write_project(root: Path, load_strategy: str, capture_block: str) -> None:
    (root / "config" / "datasets").mkdir(parents=True)
    (root / "contracts" / "raw").mkdir(parents=True)
    (root / "config" / "project.yml").write_text(
        """schema_version: 1
project:
  code: TEST
  name: Test Analytics
  repository: enterprise-snowflake-test-analytics
  owner_team: test-data
""",
        encoding="utf-8",
    )

    scd2_block = ""
    if load_strategy == "scd2_snapshot":
        scd2_block = """  scd2:
    tracked_columns: [entity_value]
"""
    elif load_strategy in {"scd2_merge", "scd2_stream_task"}:
        scd2_block = """  scd2:
    effective_at_column: source_updated_at
    order_columns: [source_updated_at, source_sequence]
    tracked_columns: [entity_value]
    operation_column: source_operation
    delete_values: [D]
    late_arriving_policy: rebuild_affected_keys
"""

    if load_strategy == "scd2_snapshot":
        change_semantics_block = """  change_semantics:
    mode: snapshot
    delete_semantics: inferred_snapshot_diff
"""
    else:
        change_semantics_block = """  change_semantics:
    mode: cdc
    operation_column: source_operation
    sequence_column: source_sequence
    delete_semantics: tombstone
"""

    (root / "config" / "datasets" / "entity.yml").write_text(
        f"""schema_version: 1
dataset:
  id: entity
  owner_team: test-data
  raw_contract: contracts/raw/entity.yml
  load_strategy: {load_strategy}
  implementation: standard
  business_key: [entity_id]
{scd2_block}""",
        encoding="utf-8",
    )
    (root / "contracts" / "raw" / "entity.yml").write_text(
        f"""schema_version: 1
contract:
  source_system: test_source
  entity: entity
  grain: one row per captured source change
  business_key: [entity_id]
  source_timestamp: source_updated_at
  columns:
    - name: entity_id
      type: VARCHAR
      nullable: false
    - name: entity_value
      type: VARCHAR
      nullable: true
    - name: source_updated_at
      type: TIMESTAMP_NTZ
      nullable: false
    - name: source_operation
      type: VARCHAR
      nullable: false
    - name: source_sequence
      type: NUMBER
      nullable: false
{change_semantics_block}{capture_block}
  breaking_change_policy: reject
""",
        encoding="utf-8",
    )


class ScdCaptureCompatibilityTests(unittest.TestCase):
    def test_snapshot_strategy_accepts_snapshot_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(
                root,
                "scd2_snapshot",
                """  capture:
    archetype: snapshot
    fidelity: current_state
    checkpoint_kind: snapshot_id
""",
            )

            self.assertEqual(validate_project_tree(root, SCHEMA_DIR), [])

    def test_snapshot_strategy_rejects_full_change_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(
                root,
                "scd2_snapshot",
                """  capture:
    archetype: full_change
    fidelity: full_change
    checkpoint_kind: source_position
    ordering_columns: [source_sequence]
    idempotency_columns: [entity_id, source_sequence]
""",
            )

            errors = validate_project_tree(root, SCHEMA_DIR)
            self.assertTrue(
                any("scd2_snapshot requires capture.archetype=snapshot" in error for error in errors)
            )

    def test_merge_strategy_requires_append_preserved_full_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(
                root,
                "scd2_merge",
                """  capture:
    archetype: net_change
    fidelity: net_change
    checkpoint_kind: source_position
    ordering_columns: [source_sequence]
    idempotency_columns: [entity_id, source_sequence]
""",
            )

            errors = validate_project_tree(root, SCHEMA_DIR)
            self.assertTrue(
                any("scd2_merge requires capture fidelity full_change/full_event" in error for error in errors)
            )
            self.assertTrue(
                any("scd2_merge requires an append-preserved event capture archetype" in error for error in errors)
            )

    def test_stream_task_requires_full_change_fidelity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(
                root,
                "scd2_stream_task",
                """  capture:
    archetype: net_change
    fidelity: net_change
    checkpoint_kind: source_position
    ordering_columns: [source_sequence]
    idempotency_columns: [entity_id, source_sequence]
""",
            )

            errors = validate_project_tree(root, SCHEMA_DIR)
            self.assertTrue(
                any("scd2_stream_task requires capture fidelity full_change/full_event" in error for error in errors)
            )
            self.assertTrue(
                any("requires an append-preserved event capture archetype" in error for error in errors)
            )


if __name__ == "__main__":
    unittest.main()
