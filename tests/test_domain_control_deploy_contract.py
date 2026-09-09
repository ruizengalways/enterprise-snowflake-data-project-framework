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

    def test_control_plane_deploys_before_silver_and_dbt(self) -> None:
        control = self.workflow.index("Deploy committed domain control-plane SQL in manifest order")
        silver = self.workflow.index("Deploy committed Silver SQL in manifest order")
        dbt = self.workflow.index("Build Gold and Semantic models")
        self.assertLess(control, silver)
        self.assertLess(silver, dbt)


if __name__ == "__main__":
    unittest.main()
