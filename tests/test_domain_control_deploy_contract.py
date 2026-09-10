import unittest
from pathlib import Path


class DomainControlDeployContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "project-deploy.yml"
        ).read_text(encoding="utf-8")

    def test_domain_control_plane_uses_committed_manifest(self) -> None:
        self.assertIn("control_plane/deploy_manifest.txt", self.workflow)
        self.assertIn("Deploy committed domain control-plane SQL in manifest order", self.workflow)
        self.assertIn("Unsafe control-plane deployment path", self.workflow)
        self.assertNotIn("esf scaffold", self.workflow)

    def test_control_preflight_runs_before_authentication_and_deployment(self) -> None:
        preflight = self.workflow.index("esf-control-preflight --project-root project")
        token = self.workflow.index("Request account-scoped GitHub OIDC token")
        control = self.workflow.index("Deploy committed domain control-plane SQL in manifest order")
        self.assertLess(preflight, token)
        self.assertLess(preflight, control)
        self.assertIn("Require current control-plane baseline before authentication", self.workflow)

    def test_missing_control_manifest_is_not_silently_skipped(self) -> None:
        validation_start = self.workflow.index("Validate committed domain control-plane deployment manifest")
        validation_end = self.workflow.index("Validate committed Silver deployment manifest")
        validation = self.workflow[validation_start:validation_end]
        deploy_start = self.workflow.index("Deploy committed domain control-plane SQL in manifest order")
        deploy_end = self.workflow.index("Deploy committed Silver SQL in manifest order")
        deploy = self.workflow[deploy_start:deploy_end]
        self.assertIn('test -f "${manifest}"', validation)
        self.assertNotIn("skipping control-plane deployment", validation.lower())
        self.assertNotIn("skipping", deploy.lower())

    def test_control_plane_deploys_before_silver_and_dbt(self) -> None:
        control = self.workflow.index("Deploy committed domain control-plane SQL in manifest order")
        silver = self.workflow.index("Deploy committed Silver SQL in manifest order")
        dbt = self.workflow.index("Build Gold and Semantic models")
        self.assertLess(control, silver)
        self.assertLess(silver, dbt)


if __name__ == "__main__":
    unittest.main()
