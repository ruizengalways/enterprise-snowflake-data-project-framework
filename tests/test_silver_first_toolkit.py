from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.metadata_validation import validate_project_tree
from enterprise_snowflake_framework.scaffold import scaffold_pipeline


PROJECT = """schema_version: 2
project:
  code: TEST
  name: Test analytics
  repository: enterprise-snowflake-test-analytics
  owner_team: data-platform
"""

RAW = """schema_version: 2
contract:
  source_system: source_a
  entity: order_status
  grain: one row per order source change
  business_key:
    - order_id
  source_timestamp: source_updated_at
  columns:
    - name: order_id
      type: VARCHAR
      nullable: false
    - name: status
      type: VARCHAR
      nullable: true
    - name: source_updated_at
      type: TIMESTAMP_NTZ
      nullable: false
    - name: source_sequence
      type: NUMBER
      nullable: false
    - name: source_operation
      type: VARCHAR
      nullable: false
    - name: ingested_at
      type: TIMESTAMP_NTZ
      nullable: false
  change_semantics:
    mode: cdc
    operation_column: source_operation
    sequence_column: source_sequence
    delete_semantics: tombstone
    delete_values: [D]
  capture_fidelity: full_change
  ordering_columns:
    - source_updated_at
    - source_sequence
  idempotency_key:
    - order_id
    - source_sequence
  breaking_change_policy: versioned_contract
"""


class SilverFirstToolkitTests(unittest.TestCase):
    def _project(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "config").mkdir()
        (root / "contracts" / "raw").mkdir(parents=True)
        (root / "config" / "project.yml").write_text(PROJECT, encoding="utf-8")
        (root / "contracts" / "raw" / "order_status.yml").write_text(RAW, encoding="utf-8")
        return tmp, root

    def test_scd2_scaffold_is_domain_owned_and_valid(self) -> None:
        tmp, root = self._project()
        self.addCleanup(tmp.cleanup)
        scaffold_pipeline(
            project_root=root,
            pattern="scd2",
            dataset_id="order_status",
            raw_contract="contracts/raw/order_status.yml",
        )
        pipeline = (root / "silver_processing" / "order_status" / "pipeline.yml").read_text(encoding="utf-8")
        self.assertIn("pattern: scd2", pipeline)
        self.assertIn("history: SILVER_CANONICAL.ORDER_STATUS_HISTORY", pipeline)
        self.assertIn("current: SILVER_CANONICAL.ORDER_STATUS_CURRENT", pipeline)
        self.assertIn("- source_sequence", pipeline)
        self.assertIn("- status", pipeline)
        self.assertEqual([], validate_project_tree(root))

    def test_pipeline_order_must_match_raw_contract(self) -> None:
        tmp, root = self._project()
        self.addCleanup(tmp.cleanup)
        destination = scaffold_pipeline(
            project_root=root,
            pattern="scd2",
            dataset_id="order_status",
            raw_contract="contracts/raw/order_status.yml",
        )
        path = destination / "pipeline.yml"
        path.write_text(path.read_text(encoding="utf-8").replace("    - source_sequence\n", ""), encoding="utf-8")
        errors = validate_project_tree(root)
        self.assertTrue(any("event_order must exactly match" in error for error in errors))

    def test_packaged_templates_are_available(self) -> None:
        package_root = Path(__import__("enterprise_snowflake_framework.scaffold", fromlist=["x"]).__file__).resolve().parent
        self.assertTrue((package_root / "templates" / "scd2" / "010_apply.sql").is_file())
        self.assertTrue((package_root / "schemas" / "silver_pipeline.schema.json").is_file())


if __name__ == "__main__":
    unittest.main()
