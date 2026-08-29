import json
import unittest
from pathlib import Path

from enterprise_snowflake_framework.dbt_vars import build_dbt_vars


class DbtVarsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.project_root = self.repo_root / "examples" / "minimal-project"
        self.schema_dir = self.repo_root / "project_schema"

    def test_builds_bounded_dataset_vars_from_valid_metadata(self) -> None:
        values = build_dbt_vars(self.project_root, self.schema_dir)

        self.assertEqual(values["esf_project"]["code"], "HEALTH")
        patient = values["esf_datasets"]["patient"]
        self.assertEqual(patient["load_strategy"], "scd2_merge")
        self.assertEqual(patient["business_key"], ["patient_id"])
        self.assertEqual(patient["source_system"], "ehr_mssql")
        self.assertEqual(patient["capture"]["archetype"], "full_change")
        self.assertEqual(patient["capture"]["fidelity"], "full_change")
        self.assertEqual(patient["capture"]["checkpoint_kind"], "source_position")
        self.assertEqual(patient["capture"]["ordering_columns"], ["source_sequence"])
        self.assertEqual(patient["capture"]["idempotency_columns"], ["patient_id", "source_sequence"])
        self.assertNotIn("columns", patient)
        self.assertNotIn("query_tag", patient)

    def test_execution_context_adds_canonical_dataset_query_tag(self) -> None:
        values = build_dbt_vars(
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

        tag = json.loads(values["esf_datasets"]["patient"]["query_tag"])
        self.assertEqual(tag["project"], "health")
        self.assertEqual(tag["environment"], "ci")
        self.assertEqual(tag["workload"], "ci")
        self.assertEqual(tag["source"], "ehr_mssql")
        self.assertEqual(tag["dataset"], "patient")
        self.assertEqual(tag["run_id"], "run-123")
        self.assertEqual(tag["git_sha"], "abc123")
        self.assertEqual(tag["pr_number"], 42)
        self.assertEqual(tag["operation"], "dbt_model")


if __name__ == "__main__":
    unittest.main()
