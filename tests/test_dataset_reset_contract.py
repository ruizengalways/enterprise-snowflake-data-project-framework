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
            "esf_execute_dataset_full_reset",
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

    def test_rendered_reset_orders_start_cleanup_complete(self) -> None:
        macro_start = self.sql.index("macro esf_dataset_full_reset_sql")
        macro_end = self.sql.index("endmacro", macro_start)
        rendered = self.sql[macro_start:macro_end]
        start = rendered.index("esf_domain_reset_start_call_sql(")
        truncate = rendered.index("truncate table if exists {{ relation }}")
        complete = rendered.index("esf_domain_reset_complete_call_sql(", truncate)
        self.assertLess(start, truncate)
        self.assertLess(truncate, complete)

    def test_executable_reset_is_stepwise_and_fail_closed(self) -> None:
        macro_start = self.sql.index("macro esf_execute_dataset_full_reset")
        macro_end = self.sql.index("endmacro", macro_start)
        executable = self.sql[macro_start:macro_end]
        self.assertIn("run_query(start_sql)", executable)
        self.assertIn("run_query('truncate table if exists ' ~ relation)", executable)
        self.assertIn("run_query(complete_sql)", executable)
        self.assertLess(executable.index("run_query(start_sql)"), executable.index("run_query('truncate table if exists ' ~ relation)"))
        self.assertLess(executable.index("run_query('truncate table if exists ' ~ relation)"), executable.index("run_query(complete_sql)"))
        self.assertIn("lifecycle stays RESETTING", executable)


if __name__ == "__main__":
    unittest.main()
