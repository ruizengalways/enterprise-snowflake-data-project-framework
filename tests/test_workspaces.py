import unittest

from enterprise_snowflake_framework.workspaces import (
    STANDARD_LAYERS,
    personal_schema_names,
    pr_schema_names,
    render_create_schema_sql,
    render_drop_schema_sql,
)


class WorkspaceTests(unittest.TestCase):
    def test_standard_layers_match_silver_first_architecture(self) -> None:
        self.assertEqual(
            STANDARD_LAYERS,
            ("BRONZE", "SILVER_CANONICAL", "GOLD_MARTS", "GOLD_SEMANTIC", "DQ"),
        )

    def test_personal_schema_normalizes_identity(self) -> None:
        self.assertEqual(
            personal_schema_names("alice.smith", ["silver_canonical", "gold_marts"]),
            ("ALICE_SMITH_SILVER_CANONICAL", "ALICE_SMITH_GOLD_MARTS"),
        )

    def test_pr_schema_names_are_deterministic(self) -> None:
        self.assertEqual(
            pr_schema_names(123, ["silver_canonical", "gold_semantic"]),
            ("PR_123_SILVER_CANONICAL", "PR_123_GOLD_SEMANTIC"),
        )

    def test_pr_create_sql_is_transient_with_zero_retention(self) -> None:
        sql = render_create_schema_sql(
            "CI_HEALTH",
            pr_schema_names(123, ["silver_canonical"]),
            transient=True,
            retention_days=0,
        )
        self.assertIn("CREATE TRANSIENT SCHEMA IF NOT EXISTS CI_HEALTH.PR_123_SILVER_CANONICAL", sql)
        self.assertIn("DATA_RETENTION_TIME_IN_DAYS = 0", sql)

    def test_drop_guard_rejects_wrong_prefix(self) -> None:
        with self.assertRaises(ValueError):
            render_drop_schema_sql(
                "CI_HEALTH",
                ["PR_124_SILVER_CANONICAL"],
                required_prefix="PR_123_",
            )

    def test_database_identifier_is_not_free_form_sql(self) -> None:
        with self.assertRaises(ValueError):
            render_create_schema_sql(
                "CI_HEALTH; DROP DATABASE PROD_HEALTH",
                ["PR_123_SILVER_CANONICAL"],
                transient=True,
                retention_days=0,
            )


if __name__ == "__main__":
    unittest.main()
