import json
import unittest
from pathlib import Path

from enterprise_snowflake_framework.config_snapshot import (
    build_dataset_config_snapshot,
    canonical_json,
)
from enterprise_snowflake_framework.dbt_vars import build_dbt_vars


class DatasetConfigSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.project_root = self.repo_root / "examples" / "minimal-project"
        self.schema_dir = self.repo_root / "project_schema"

    def test_canonical_json_is_order_independent(self) -> None:
        left = {"b": 2, "a": {"y": 2, "x": 1}}
        right = {"a": {"x": 1, "y": 2}, "b": 2}
        self.assertEqual(canonical_json(left), canonical_json(right))

    def test_snapshot_hash_changes_when_strategy_changes(self) -> None:
        dataset_document = {
            "schema_version": 1,
            "dataset": {
                "id": "provider",
                "owner_team": "health-data",
                "raw_contract": "contracts/raw/provider.yml",
                "load_strategy": "scd1_merge",
                "implementation": "standard",
                "business_key": ["provider_id"],
            },
        }
        raw_document = {
            "schema_version": 1,
            "contract": {
                "source_system": "ehr_mssql",
                "entity": "provider",
                "grain": "one row per provider",
                "business_key": ["provider_id"],
                "change_semantics": {"mode": "upsert"},
                "cadence": "hourly",
                "retention_days": 30,
                "breaking_change_policy": "versioned_contract",
            },
        }
        scd1 = build_dataset_config_snapshot(dataset_document, raw_document)
        changed = json.loads(json.dumps(dataset_document))
        changed["dataset"]["load_strategy"] = "full_refresh"
        full_refresh = build_dataset_config_snapshot(changed, raw_document)
        self.assertNotEqual(scd1["config_hash"], full_refresh["config_hash"])
        self.assertEqual(len(scd1["config_hash"]), 64)

    def test_dbt_vars_expose_static_snapshot_separately_from_runtime_tag(self) -> None:
        static_values = build_dbt_vars(self.project_root, self.schema_dir)
        runtime_values = build_dbt_vars(
            self.project_root,
            self.schema_dir,
            query_context={
                "environment": "ci",
                "workload": "ci",
                "run_id": "run-123",
                "git_sha": "abc123",
                "pr_number": 42,
            },
        )

        static_snapshot = static_values["esf_dataset_snapshots"]["patient"]
        runtime_snapshot = runtime_values["esf_dataset_snapshots"]["patient"]
        self.assertEqual(static_snapshot, runtime_snapshot)
        self.assertEqual(static_snapshot["config_schema_version"], 1)
        self.assertEqual(len(static_snapshot["config_hash"]), 64)
        payload = json.loads(static_snapshot["config_json"])
        self.assertEqual(payload["dataset"]["id"], "patient")
        self.assertEqual(payload["dataset"]["load_strategy"], "scd2_merge")
        self.assertEqual(payload["source_contract"]["source_system"], "ehr_mssql")
        self.assertNotIn("query_tag", static_snapshot["config_json"])
        self.assertIn("query_tag", runtime_values["esf_datasets"]["patient"])


if __name__ == "__main__":
    unittest.main()
