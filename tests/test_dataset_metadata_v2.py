import json
import unittest
from pathlib import Path

from enterprise_snowflake_framework.dataset_metadata import (
    legacy_dataset_view,
    normalize_dataset_document,
    validate_execution_model,
)
from enterprise_snowflake_framework.dbt_vars import build_dbt_vars
from enterprise_snowflake_framework.metadata_validation import validate_project_tree


class DatasetMetadataV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.schema_dir = self.repo_root / "project_schema"
        self.project_root = self.repo_root / "examples" / "readable-project"

    def test_mixed_strategy_project_validates_as_one_domain(self) -> None:
        self.assertEqual(validate_project_tree(self.project_root, self.schema_dir), [])

    def test_dbt_vars_expose_strategy_and_execution_as_separate_dimensions(self) -> None:
        values = build_dbt_vars(self.project_root, self.schema_dir)
        datasets = values["esf_datasets"]

        self.assertEqual(datasets["reference_full"]["load"]["strategy"], "full_refresh")
        self.assertEqual(datasets["events_append"]["load"]["strategy"], "append_only")
        self.assertEqual(datasets["current_merge"]["load"]["strategy"], "incremental_merge")
        self.assertEqual(datasets["dimension_scd1"]["load"]["strategy"], "scd1")
        self.assertEqual(datasets["dimension_scd2"]["load"]["strategy"], "scd2")
        self.assertEqual(datasets["current_dynamic"]["load"]["execution"]["mode"], "dynamic_table")
        self.assertEqual(datasets["current_dynamic"]["load"]["execution"]["target_lag"], "10 minutes")
        self.assertEqual(datasets["special_custom"]["load"]["execution"]["mode"], "custom")

    def test_v1_scd2_merge_normalizes_without_flag_day_migration(self) -> None:
        document = {
            "schema_version": 1,
            "dataset": {
                "id": "vehicle_status",
                "owner_team": "transport-data",
                "raw_contract": "contracts/raw/vehicle_status.yml",
                "load_strategy": "scd2_merge",
                "implementation": "standard",
                "business_key": ["vehicle_id"],
                "scd2": {"tracked_columns": ["status"]},
            },
        }
        canonical = normalize_dataset_document(document)
        self.assertEqual(canonical["load"]["strategy"], "scd2")
        self.assertEqual(canonical["load"]["execution"]["mode"], "dbt_batch")
        self.assertEqual(legacy_dataset_view(canonical)["load_strategy"], "scd2_merge")

    def test_execution_compatibility_rejects_scd2_dynamic_table(self) -> None:
        canonical = {
            "id": "history",
            "owner_team": "data",
            "raw_contract": "contracts/raw/history.yml",
            "load": {
                "strategy": "scd2",
                "execution": {"mode": "dynamic_table", "target_lag": "10 minutes"},
                "business_key": ["id"],
                "scd2": {"tracked_columns": ["value"]},
            },
        }
        errors = validate_execution_model(canonical, Path("history.yml"))
        self.assertTrue(any("does not support execution.mode dynamic_table" in error for error in errors))

    def test_v2_config_snapshot_contains_canonical_load_object(self) -> None:
        values = build_dbt_vars(self.project_root, self.schema_dir)
        snapshot = values["esf_dataset_snapshots"]["dimension_scd2"]
        payload = json.loads(snapshot["config_json"])
        self.assertEqual(payload["dataset"]["load"]["strategy"], "scd2")
        self.assertEqual(payload["dataset"]["load"]["execution"]["mode"], "dbt_batch")


class ReadableModelMacroContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.macro = (
            self.repo_root / "dbt_package" / "macros" / "loading" / "strategies.sql"
        ).read_text(encoding="utf-8")

    def test_apply_macro_configures_materialization_without_business_sql(self) -> None:
        text = self.macro.lower()
        self.assertIn("macro esf_apply_dataset_config", text)
        self.assertIn("materialized='dynamic_table'", text)
        self.assertIn("incremental_strategy='append'", text)
        self.assertIn("incremental_strategy='merge'", text)
        self.assertNotIn("merge into", text)
        self.assertNotIn("group by", text)
        self.assertNotIn("case when", text)


if __name__ == "__main__":
    unittest.main()
