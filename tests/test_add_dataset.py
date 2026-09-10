from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.cli import _build_parser
from enterprise_snowflake_framework.dataset_management import add_dataset
from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.plan import build_source_plan
from enterprise_snowflake_framework.source_management import add_source
from enterprise_snowflake_framework.validation import validate_project_tree


RAW_TEMPLATE = """schema_version: 2
contract:
  source_system: {source}
  entity: {dataset}
  grain: one row per source change
  business_key: [id]
  source_timestamp: source_updated_at
  columns:
    - {{name: id, type: VARCHAR, nullable: false}}
    - {{name: payload, type: VARCHAR, nullable: true}}
    - {{name: source_updated_at, type: TIMESTAMP_NTZ, nullable: false}}
    - {{name: source_sequence, type: NUMBER, nullable: false}}
    - {{name: ingested_at, type: TIMESTAMP_LTZ, nullable: false}}
  change_semantics:
    mode: append
    sequence_column: source_sequence
    delete_semantics: none
  capture_fidelity: full_event
  ordering_columns: [source_updated_at, source_sequence]
  idempotency_key: [id, source_sequence]
  breaking_change_policy: versioned_contract
"""


class AddDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(self.root)
        add_source(self.root, "fleet_mssql")

    def _raw(self, source: str, dataset: str) -> Path:
        path = self.root / "contracts" / "raw" / source / f"{dataset}.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(RAW_TEMPLATE.format(source=source, dataset=dataset), encoding="utf-8")
        return path

    def test_add_dataset_declares_only_manifest_then_plan_sees_new_work(self) -> None:
        self._raw("fleet_mssql", "customer")

        result = add_dataset(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            pattern="append",
        )

        self.assertTrue(result.created)
        self.assertEqual("contracts/raw/fleet_mssql/customer.yml", result.raw_contract)
        manifest = yaml.safe_load(result.manifest.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "pattern": "append",
                "raw_contract": "contracts/raw/fleet_mssql/customer.yml",
            },
            manifest["datasets"]["customer"],
        )
        self.assertFalse(
            (self.root / "silver_processing" / "fleet_mssql" / "customer").exists()
        )
        plan = build_source_plan(self.root, "fleet_mssql")
        self.assertEqual(1, plan.manifest_count)
        self.assertEqual(["customer"], [item.dataset_id for item in plan.new])
        self.assertEqual([], validate_project_tree(self.root))

    def test_round_trip_edit_preserves_existing_comments_and_order(self) -> None:
        self._raw("fleet_mssql", "orders")
        self._raw("fleet_mssql", "customer")
        manifest = self.root / "config" / "sources" / "fleet_mssql.yml"
        manifest.write_text(
            """# domain-reviewed source manifest
schema_version: 1
source:
  id: fleet_mssql
  owner: transport  # owning team stays visible

datasets:
  orders:  # existing domain-owned declaration
    pattern: append
    raw_contract: contracts/raw/fleet_mssql/orders.yml
""",
            encoding="utf-8",
        )

        add_dataset(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            pattern="scd1",
        )

        text = manifest.read_text(encoding="utf-8")
        self.assertIn("# domain-reviewed source manifest", text)
        self.assertIn("# owning team stays visible", text)
        self.assertIn("# existing domain-owned declaration", text)
        self.assertLess(text.index("orders:"), text.index("customer:"))
        self.assertIn("pattern: scd1", text)
        self.assertIn("raw_contract: contracts/raw/fleet_mssql/customer.yml", text)
        self.assertEqual([], validate_project_tree(self.root))

    def test_existing_dataset_is_strict_no_op_even_if_new_arguments_differ(self) -> None:
        self._raw("fleet_mssql", "customer")
        first = add_dataset(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            pattern="append",
        )
        before = first.manifest.read_bytes()

        repeated = add_dataset(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            pattern="full_refresh",
            raw_contract="contracts/raw/fleet_mssql/does_not_exist.yml",
        )

        self.assertFalse(repeated.created)
        self.assertEqual("already exists", repeated.reason)
        self.assertEqual(before, repeated.manifest.read_bytes())

    def test_rejects_cross_source_or_mismatched_raw_contract(self) -> None:
        self._raw("gtfs_api", "customer")
        with self.assertRaises(ValueError):
            add_dataset(
                project_root=self.root,
                source_id="fleet_mssql",
                dataset_id="customer",
                pattern="append",
                raw_contract="contracts/raw/gtfs_api/customer.yml",
            )

        wrong = self.root / "contracts" / "raw" / "fleet_mssql" / "customer.yml"
        wrong.parent.mkdir(parents=True, exist_ok=True)
        wrong.write_text(
            RAW_TEMPLATE.format(source="gtfs_api", dataset="customer"),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            add_dataset(
                project_root=self.root,
                source_id="fleet_mssql",
                dataset_id="customer",
                pattern="append",
            )

        manifest = yaml.safe_load(
            (self.root / "config" / "sources" / "fleet_mssql.yml").read_text(encoding="utf-8")
        )
        self.assertEqual({}, manifest["datasets"])

    def test_rejects_invalid_ids_and_missing_contract(self) -> None:
        with self.assertRaises(ValueError):
            add_dataset(self.root, "fleet_mssql", "Customer", "append")
        with self.assertRaises(ValueError):
            add_dataset(self.root, "../fleet", "customer", "append")
        with self.assertRaises(FileNotFoundError):
            add_dataset(self.root, "fleet_mssql", "customer", "append")

    def test_cli_exposes_narrow_add_dataset_without_force(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "add-dataset",
                "customer",
                "--source",
                "fleet_mssql",
                "--pattern",
                "scd2",
            ]
        )
        self.assertEqual("add-dataset", args.command)
        self.assertEqual("customer", args.dataset_id)
        self.assertIsNone(args.raw_contract)
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "add-dataset",
                    "customer",
                    "--source",
                    "fleet_mssql",
                    "--pattern",
                    "scd2",
                    "--force",
                ]
            )


if __name__ == "__main__":
    unittest.main()
