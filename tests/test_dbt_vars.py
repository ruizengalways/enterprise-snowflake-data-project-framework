import unittest
from pathlib import Path

from enterprise_snowflake_framework.dbt_vars import build_dbt_vars


class DbtVarsTests(unittest.TestCase):
    def test_builds_bounded_dataset_vars_from_valid_metadata(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        values = build_dbt_vars(repo_root / "examples" / "minimal-project", repo_root / "project_schema")

        self.assertEqual(values["esf_project"]["code"], "HEALTH")
        patient = values["esf_datasets"]["patient"]
        self.assertEqual(patient["load_strategy"], "scd2_snapshot")
        self.assertEqual(patient["business_key"], ["patient_id"])
        self.assertNotIn("columns", patient)


if __name__ == "__main__":
    unittest.main()
