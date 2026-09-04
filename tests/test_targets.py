import unittest

from enterprise_snowflake_framework.targets import resolve_dbt_target


class TargetResolverTests(unittest.TestCase):
    def test_personal_dev_target(self) -> None:
        target = resolve_dbt_target("HEALTH", "dev", "transform", developer="alice.smith")
        self.assertEqual(target.database, "DEV_HEALTH")
        self.assertEqual(target.warehouse, "WH_HEALTH_TRANSFORM")
        self.assertEqual(target.schema_prefix, "ALICE_SMITH")

    def test_shared_dev_target_has_no_prefix(self) -> None:
        target = resolve_dbt_target("HEALTH", "dev", "transform")
        self.assertEqual(target.schema_prefix, "")
        self.assertEqual(target.default_schema, "SILVER_STAGING")

    def test_pr_ci_target(self) -> None:
        target = resolve_dbt_target("TRANSPORT", "ci", "ci", pr_number=123)
        self.assertEqual(target.database, "CI_TRANSPORT")
        self.assertEqual(target.warehouse, "WH_TRANSPORT_CI")
        self.assertEqual(target.schema_prefix, "PR_123")
        self.assertEqual(target.default_schema, "SILVER_STAGING")

    def test_uat_and_prod_use_stable_schema_names(self) -> None:
        for environment in ("uat", "prod"):
            target = resolve_dbt_target("HEALTH", environment, "query")
            self.assertEqual(target.schema_prefix, "")
            self.assertEqual(target.database, f"{environment.upper()}_HEALTH")

    def test_custom_default_schema_must_be_standard_layer(self) -> None:
        target = resolve_dbt_target(
            "HEALTH", "dev", "transform", default_schema="silver_canonical"
        )
        self.assertEqual(target.default_schema, "SILVER_CANONICAL")
        with self.assertRaises(ValueError):
            resolve_dbt_target("HEALTH", "dev", "transform", default_schema="staging")

    def test_ci_requires_pr_number_and_ci_workload(self) -> None:
        with self.assertRaises(ValueError):
            resolve_dbt_target("HEALTH", "ci", "ci")
        with self.assertRaises(ValueError):
            resolve_dbt_target("HEALTH", "ci", "transform", pr_number=1)

    def test_non_ci_rejects_pr_number_and_ci_workload(self) -> None:
        with self.assertRaises(ValueError):
            resolve_dbt_target("HEALTH", "dev", "ci")
        with self.assertRaises(ValueError):
            resolve_dbt_target("HEALTH", "prod", "query", pr_number=1)

    def test_non_dev_rejects_developer_prefix(self) -> None:
        with self.assertRaises(ValueError):
            resolve_dbt_target("HEALTH", "prod", "query", developer="alice")


if __name__ == "__main__":
    unittest.main()
