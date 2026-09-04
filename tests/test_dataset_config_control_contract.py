import json
import unittest
from pathlib import Path


class DatasetConfigControlContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_domain_config_macro_uses_only_scoped_platform_surface(self) -> None:
        path = self.repo_root / "dbt_package" / "macros" / "operations" / "dataset_config.sql"
        text = path.read_text(encoding="utf-8").upper()
        self.assertIn("PLATFORM_CONTROL.CONFIG.", text)
        self.assertIn("_DATASET_CONFIG_SNAPSHOT", text)
        self.assertIn("_REGISTER_DATASET_CONFIG_SNAPSHOT", text)
        self.assertNotIn("INSERT INTO PLATFORM_CONTROL.CONFIG.DATASET_CONFIG_SNAPSHOT", text)
        self.assertNotIn("UPDATE PLATFORM_CONTROL.CONFIG.DATASET_CONFIG_SNAPSHOT", text)
        self.assertNotIn("DELETE FROM PLATFORM_CONTROL.CONFIG.DATASET_CONFIG_SNAPSHOT", text)
        self.assertNotIn("P_PROJECT_CODE", text)
        self.assertNotIn("P_ENVIRONMENT", text)

    def test_scd1_is_explicit_standard_strategy(self) -> None:
        schema = json.loads(
            (self.repo_root / "project_schema" / "dataset.schema.json").read_text(encoding="utf-8")
        )
        strategies = schema["properties"]["dataset"]["properties"]["load_strategy"]["enum"]
        self.assertIn("scd1_merge", strategies)
        macro = (
            self.repo_root / "dbt_package" / "macros" / "loading" / "strategies.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("['incremental_merge', 'scd1_merge']", macro)


if __name__ == "__main__":
    unittest.main()
