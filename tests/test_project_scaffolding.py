from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.cli import _build_parser
from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.plan import build_source_plan
from enterprise_snowflake_framework.scaffold import scaffold_all, scaffold_pipeline
from enterprise_snowflake_framework.source_management import add_source
from enterprise_snowflake_framework.validation import validate_project_tree


RAW_TEMPLATE = """schema_version: 2
contract:
  source_system: {source}
  entity: {dataset}
  grain: one row per source change
  business_key:
    - id
  source_timestamp: source_updated_at
  columns:
    - name: id
      type: VARCHAR
      nullable: false
    - name: name
      type: VARCHAR
      nullable: true
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
    - id
    - source_sequence
  breaking_change_policy: versioned_contract
"""


class ProjectScaffoldingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-test-analytics"
        initialize_project(self.root)
        self.template_root = Path(
            __import__("enterprise_snowflake_framework.scaffold", fromlist=["x"]).__file__
        ).resolve().parent / "templates"

    def _configure_source(self, source: str, datasets: list[str], pattern: str = "scd2") -> None:
        result = add_source(self.root, source)
        if not result.created and not (self.root / "config" / "sources" / f"{source}.yml").is_file():
            self.fail("source setup is unexpectedly partial")
        raw_root = self.root / "contracts" / "raw" / source
        raw_root.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 1,
            "source": {"id": source, "owner": "test"},
            "datasets": {},
        }
        for dataset in datasets:
            raw_path = raw_root / f"{dataset}.yml"
            raw_path.write_text(RAW_TEMPLATE.format(source=source, dataset=dataset), encoding="utf-8")
            manifest["datasets"][dataset] = {
                "pattern": pattern,
                "raw_contract": f"contracts/raw/{source}/{dataset}.yml",
            }
        (self.root / "config" / "sources" / f"{source}.yml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )

    def _extend_source(self, source: str, datasets: list[str], pattern: str = "scd2") -> None:
        manifest_path = self.root / "config" / "sources" / f"{source}.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        raw_root = self.root / "contracts" / "raw" / source
        for dataset in datasets:
            (raw_root / f"{dataset}.yml").write_text(
                RAW_TEMPLATE.format(source=source, dataset=dataset), encoding="utf-8"
            )
            manifest["datasets"][dataset] = {
                "pattern": pattern,
                "raw_contract": f"contracts/raw/{source}/{dataset}.yml",
            }
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    def test_init_project_is_non_destructive_and_reentrant(self) -> None:
        readme = self.root / "README.md"
        readme.write_text("DOMAIN README\n", encoding="utf-8")
        result = initialize_project(self.root)
        self.assertEqual("DOMAIN README\n", readme.read_text(encoding="utf-8"))
        self.assertIn(readme, result.skipped_files)
        self.assertTrue((self.root / "dbt" / "models" / "semantic").is_dir())
        self.assertEqual([], validate_project_tree(self.root))

    def test_add_source_is_conservative_if_any_source_path_exists(self) -> None:
        partial = self.root / "ingestion" / "fleet_mssql"
        partial.mkdir()
        result = add_source(self.root, "fleet_mssql")
        self.assertFalse(result.created)
        self.assertFalse((self.root / "config" / "sources" / "fleet_mssql.yml").exists())
        self.assertEqual([], list(partial.iterdir()))

    def test_40_then_60_scaffold_creates_only_20_and_preserves_custom_sql(self) -> None:
        first = ["customer"] + [f"table_{index:02d}" for index in range(1, 40)]
        self._configure_source("fleet_mssql", first)
        first_result = scaffold_all(
            project_root=self.root, source_id="fleet_mssql", template_root=self.template_root
        )
        self.assertEqual(40, len(first_result.created))
        self.assertEqual(0, len(first_result.skipped))

        custom_path = self.root / "silver_processing" / "fleet_mssql" / "customer" / "010_apply.sql"
        custom_text = "-- DOMAIN CUSTOM LOGIC - MUST SURVIVE\nselect 1;\n"
        custom_path.write_text(custom_text, encoding="utf-8")

        added = [f"new_table_{index:02d}" for index in range(1, 21)]
        self._extend_source("fleet_mssql", added)
        plan = build_source_plan(self.root, "fleet_mssql")
        self.assertEqual(60, plan.manifest_count)
        self.assertEqual(40, len(plan.existing))
        self.assertEqual(20, len(plan.new))
        self.assertEqual(0, plan.overwrite_count)

        second_result = scaffold_all(
            project_root=self.root, source_id="fleet_mssql", template_root=self.template_root
        )
        self.assertEqual(20, len(second_result.created))
        self.assertEqual(40, len(second_result.skipped))
        self.assertEqual(0, second_result.overwritten)
        self.assertEqual(custom_text, custom_path.read_text(encoding="utf-8"))

    def test_existing_dataset_directory_is_never_completed_or_rewritten(self) -> None:
        self._configure_source("fleet_mssql", ["customer"])
        destination = self.root / "silver_processing" / "fleet_mssql" / "customer"
        destination.mkdir(parents=True)
        marker = destination / "010_apply.sql"
        marker.write_text("-- CUSTOM ONLY\n", encoding="utf-8")

        result = scaffold_pipeline(
            project_root=self.root,
            source_id="fleet_mssql",
            pattern="scd2",
            dataset_id="customer",
            template_root=self.template_root,
        )
        self.assertFalse(result.created)
        self.assertEqual("-- CUSTOM ONLY\n", marker.read_text(encoding="utf-8"))
        self.assertFalse((destination / "pipeline.yml").exists())
        self.assertIn("pipeline.yml", result.missing_standard_files)

    def test_scaffold_all_is_scoped_to_one_source(self) -> None:
        self._configure_source("fleet_mssql", ["customer", "orders"])
        self._configure_source("gtfs_api", ["vehicle_position", "trip_update"])
        scaffold_all(project_root=self.root, source_id="fleet_mssql", template_root=self.template_root)
        fleet_file = self.root / "silver_processing" / "fleet_mssql" / "customer" / "010_apply.sql"
        fleet_file.write_text("-- FLEET DOMAIN CUSTOM\n", encoding="utf-8")

        result = scaffold_all(project_root=self.root, source_id="gtfs_api", template_root=self.template_root)
        self.assertEqual(2, len(result.created))
        self.assertEqual("-- FLEET DOMAIN CUSTOM\n", fleet_file.read_text(encoding="utf-8"))
        self.assertEqual(
            {"customer", "orders"},
            {
                path.name
                for path in (self.root / "silver_processing" / "fleet_mssql").iterdir()
                if path.is_dir()
            },
        )

    def test_scd2_pipeline_metadata_does_not_repeat_raw_contract_semantics(self) -> None:
        self._configure_source("fleet_mssql", ["customer"])
        result = scaffold_pipeline(
            project_root=self.root,
            source_id="fleet_mssql",
            pattern="scd2",
            dataset_id="customer",
            template_root=self.template_root,
        )
        pipeline = (result.destination / "pipeline.yml").read_text(encoding="utf-8")
        self.assertIn("schema_version: 1", pipeline)
        self.assertIn("tracked_columns:", pipeline)
        self.assertNotIn("business_key:", pipeline)
        self.assertNotIn("event_order:", pipeline)
        self.assertNotIn("idempotency_key:", pipeline)
        self.assertNotIn("effective_at:", pipeline)
        self.assertNotIn("delete:", pipeline)
        self.assertEqual([], validate_project_tree(self.root))

    def test_cli_has_no_force_escape_hatch(self) -> None:
        with self.assertRaises(SystemExit):
            _build_parser().parse_args(
                ["scaffold", "scd2", "customer", "--source", "fleet_mssql", "--force"]
            )


if __name__ == "__main__":
    unittest.main()
