import unittest

from enterprise_snowflake_framework.migration_deployment import BOOTSTRAP_SQL, SnowCliClient


class MigrationHistoryContractTests(unittest.TestCase):
    def test_bootstrap_history_contains_required_audit_fields(self) -> None:
        for field in (
            "DEPLOYMENT_ATTEMPT_ID",
            "MIGRATION_SCOPE",
            "MIGRATION_PATH",
            "CHECKSUM_SHA256",
            "MANIFEST_POSITION",
            "PROJECT_GIT_SHA",
            "FRAMEWORK_GIT_SHA",
            "STATUS",
            "STARTED_AT",
            "FINISHED_AT",
            "ERROR_CODE",
            "ERROR_DETAILS",
            "GITHUB_RUN_ID",
            "OPERATOR_REASON",
        ):
            self.assertIn(field, BOOTSTRAP_SQL)

    def test_snow_cli_client_uses_same_workload_identity_shape_as_deploy_workflow(self) -> None:
        client = SnowCliClient(
            {
                "SNOWFLAKE_ACCOUNT": "example-account",
                "SNOWFLAKE_USER": "SU_GITHUB_TEST_DEPLOY",
                "SNOWFLAKE_ROLE": "AR_TEST_DEPLOY",
                "SNOWFLAKE_WAREHOUSE": "WH_TEST_TRANSFORM",
                "SNOWFLAKE_DATABASE": "DEV_TEST",
                "ESF_SNOWFLAKE_AUTHENTICATOR": "WORKLOAD_IDENTITY",
                "ESF_SNOWFLAKE_WORKLOAD_IDENTITY_PROVIDER": "OIDC",
            }
        )
        command = client._base_command()
        self.assertIn("--temporary-connection", command)
        self.assertIn("WORKLOAD_IDENTITY", command)
        self.assertIn("--workload-identity-provider", command)
        self.assertIn("OIDC", command)
        self.assertIn("--enhanced-exit-codes", command)


if __name__ == "__main__":
    unittest.main()
