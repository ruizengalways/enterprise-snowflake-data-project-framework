from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_CONTROL = ROOT / "dbt_package/macros/operations/domain_control.sql"


class DomainControlContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = DOMAIN_CONTROL.read_text(encoding="utf-8")

    def test_project_runtime_helpers_are_present(self) -> None:
        for macro in (
            "esf_domain_control_relation",
            "esf_domain_control_procedure",
            "esf_domain_checkpoint_read_sql",
            "esf_domain_checkpoint_advance_call_sql",
            "esf_domain_pipeline_run_start_call_sql",
            "esf_domain_pipeline_run_finish_call_sql",
            "esf_domain_record_check_result_sql",
        ):
            self.assertIn(f"macro {macro}", self.sql)

    def test_domain_object_names_are_derived_from_project_code(self) -> None:
        self.assertIn("code ~ '_' ~ normalized_object", self.sql)
        self.assertIn("code ~ '_' ~ normalized_procedure", self.sql)
        self.assertIn("^[A-Z][A-Z0-9_]{1,31}$", self.sql)

    def test_safe_write_helpers_do_not_expose_project_or_environment_parameters(self) -> None:
        self.assertNotIn("P_PROJECT_CODE", self.sql)
        self.assertNotIn("P_ENVIRONMENT", self.sql)
        self.assertNotIn("'HEALTH'", self.sql)
        self.assertNotIn("'TRANSPORT'", self.sql)

    def test_quality_write_routes_through_guarded_procedure(self) -> None:
        self.assertIn("RECORD_PIPELINE_CHECK_RESULT", self.sql)
        self.assertIn("for check_row in check_cursor do", self.sql.lower())
        self.assertIn("call {{ procedure_relation }}", self.sql)


if __name__ == "__main__":
    unittest.main()
