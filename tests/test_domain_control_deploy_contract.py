import unittest
from pathlib import Path


class DomainControlDeployContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "project-deploy.yml"
        ).read_text(encoding="utf-8")

    def test_domain_control_plane_uses_committed_manifest(self) -> None:
        self.assertIn("control_plane/deploy_manifest.txt", self.workflow)
        self.assertIn("Unsafe control-plane deployment path", self.workflow)
        self.assertIn("esf-migrate deploy", self.workflow)
        self.assertNotIn("esf scaffold", self.workflow)

    def test_control_preflight_runs_before_authentication_and_migration_runner(self) -> None:
        preflight = self.workflow.index("esf-control-preflight --project-root project")
        token = self.workflow.index("Request account-scoped GitHub OIDC token")
        migrate = self.workflow.index("esf-migrate deploy")
        self.assertLess(preflight, token)
        self.assertLess(token, migrate)
        self.assertIn("Require current control-plane baseline before authentication", self.workflow)

    def test_missing_control_manifest_is_not_silently_skipped(self) -> None:
        validation_start = self.workflow.index("Validate committed domain control-plane deployment manifest")
        validation_end = self.workflow.index("Validate committed Silver deployment manifest")
        validation = self.workflow[validation_start:validation_end]
        self.assertIn('test -f "${manifest}"', validation)
        self.assertNotIn("skipping control-plane deployment", validation.lower())

    def test_apply_once_migrations_run_before_dbt(self) -> None:
        migrate = self.workflow.index("Apply committed CONTROL and SILVER migrations once")
        dbt_debug = self.workflow.index("Verify dbt connection")
        dbt_build = self.workflow.index("Build Gold and Semantic models")
        self.assertLess(migrate, dbt_debug)
        self.assertLess(dbt_debug, dbt_build)

    def test_old_full_manifest_replay_loops_are_removed(self) -> None:
        self.assertNotIn("Deploy committed domain control-plane SQL in manifest order", self.workflow)
        self.assertNotIn("Deploy committed Silver SQL in manifest order", self.workflow)
        self.assertNotIn('echo "Applying ${path}"', self.workflow)

    def test_same_domain_environment_deployments_are_serialized(self) -> None:
        self.assertIn("concurrency:", self.workflow)
        self.assertIn("group: esf-deploy-${{ inputs.project_code }}-${{ inputs.environment }}", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)


if __name__ == "__main__":
    unittest.main()
