import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.metadata_validation import validate_project_tree


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "project_schema"


class MetadataValidationTests(unittest.TestCase):
    def test_minimal_project_example_passes(self) -> None:
        errors = validate_project_tree(REPO_ROOT / "examples" / "minimal-project", SCHEMA_DIR)
        self.assertEqual(errors, [])

    def test_keyed_strategy_requires_business_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
            (root / "config" / "datasets" / "entity.yml").write_text(
                """schema_version: 1
dataset:
  id: entity
  owner_team: test-data
  raw_contract: contracts/raw/entity.yml
  load_strategy: incremental_merge
  implementation: standard
""",
                encoding="utf-8",
            )
            (root / "contracts" / "raw" / "entity.yml").write_text(
                """schema_version: 1
contract:
  source_system: test_source
  entity: entity
  grain: one row per entity
  business_key: [entity_id]
  columns:
    - name: entity_id
      type: VARCHAR
      nullable: false
  change_semantics:
    mode: snapshot
  breaking_change_policy: reject
""",
                encoding="utf-8",
            )

            errors = validate_project_tree(root, SCHEMA_DIR)
            self.assertTrue(any("requires dataset.business_key" in error for error in errors))

    def test_cdc_columns_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
            (root / "config" / "datasets" / "entity.yml").write_text(
                """schema_version: 1
dataset:
  id: entity
  owner_team: test-data
  raw_contract: contracts/raw/entity.yml
  load_strategy: full_refresh
  implementation: standard
""",
                encoding="utf-8",
            )
            (root / "contracts" / "raw" / "entity.yml").write_text(
                """schema_version: 1
contract:
  source_system: test_source
  entity: entity
  grain: one row per source change
  business_key: [entity_id]
  columns:
    - name: entity_id
      type: VARCHAR
      nullable: false
  change_semantics:
    mode: cdc
    operation_column: source_operation
    sequence_column: source_sequence
  breaking_change_policy: reject
""",
                encoding="utf-8",
            )

            errors = validate_project_tree(root, SCHEMA_DIR)
            self.assertTrue(any("operation_column column is not declared" in error for error in errors))
            self.assertTrue(any("sequence_column column is not declared" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
