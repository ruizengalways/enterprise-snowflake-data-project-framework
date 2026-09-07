from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESET_MACROS = ROOT / "dbt_package/macros/operations/reset.sql"


class DatasetResetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = RESET_MACROS.read_text(encoding="utf-8")

    def test_reset_is_separate_bounded_domain_api(self) -> None:
        for macro in (
            "esf_domain_reset_relation",
            "esf_domain_reset_procedure",
            "esf_domain_reset_start_call_sql",
            "esf_domain_reset_complete_call_sql",
            "esf_dataset_full_reset_sql",
        ):
            self.assertIn(f"macro {macro}", self.sql)
        self.assertIn("DATASET_RESET_START", self.sql)
        self.assertIn("DATASET_RESET_COMPLETE", self.sql)
        self.assertNotIn("P_PROJECT_CODE", self.sql)
        self.assertNotIn("P_ENVIRONMENT", self.sql)

    def test_cleanup_relations_are_explicit_and_validated(self) -> None:
        self.assertIn("full reset requires a non-empty explicit relations list", self.sql)
        self.assertIn("fully-qualified unquoted DATABASE.SCHEMA.OBJECT", self.sql)
        self.assertIn("truncate table if exists {{ relation }}", self.sql.lower())
        self.assertNotIn("repair", self.sql.lower().split("RESET is deliberately separate from repair/replay".lower())[-1])

    def test_reset_orders_start_cleanup_complete(self) -> None:
        start = self.sql.index("esf_domain_reset_start_call_sql(")
        truncate = self.sql.index("truncate table if exists {{ relation }}")
        complete = self.sql.index("esf_domain_reset_complete_call_sql(", truncate)
        self.assertLess(start, truncate)
        self.assertLess(truncate, complete)


if __name__ == "__main__":
    unittest.main()
