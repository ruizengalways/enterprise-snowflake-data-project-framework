import unittest

from enterprise_snowflake_framework.workspaces import (
    personal_schema_names,
    pr_schema_names,
    render_create_schema_sql,
    render_drop_schema_sql,
)


class WorkspaceTests(unittest.TestCase):
    def test_personal_schema_normalizes_identity(self) -> None:
        self.assertEqual(
            personal_schema_names("alice.smith", ["staging", "marts"]),
            ("ALICE_SMITH_STAGING", "ALICE_SMITH_MARTS"),
        )

    def test_pr_schema_names_are_deterministic(self) -> None:
        self.assertEqual(
            pr_schema_names(123, ["staging", "semantic"]),
            ("PR_123_STAGING", "PR_123_SEMANTIC"),
        )

    def test_pr_create_sql_is_transient_with_zero_retention(self) -> None:
        sql = render_create_schema_sql(
            "CI_HEALTH",
            pr_schema_names(123, ["staging"]),
            transient=True,
            retention_days=0,
        )
        self.assertIn("CREATE TRANSIENT SCHEMA IF NOT EXISTS CI_HEALTH.PR_123_STAGING", sql)
        self.assertIn("DATA_RETENTION_TIME_IN_DAYS = 0", sql)

    def test_drop_guard_rejects_wrong_prefix(self) -> None:
        with self.assertRaises(ValueError):
            render_drop_schema_sql(
                "CI_HEALTH",
                ["PR_124_STAGING"],
                required_prefix="PR_123_",
            )

    def test_database_identifier_is_not_free_form_sql(self) -> None:
        with self.assertRaises(ValueError):
            render_create_schema_sql(
                "CI_HEALTH; DROP DATABASE PROD_HEALTH",
                ["PR_123_STAGING"],
                transient=True,
                retention_days=0,
            )


if __name__ == "__main__":
    unittest.main()
