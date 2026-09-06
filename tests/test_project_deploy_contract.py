import unittest
from pathlib import Path


class ProjectDeployContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "project-deploy.yml"
        ).read_text(encoding="utf-8")

    def test_deploy_uses_medallion_default_and_validated_context(self) -> None:
        self.assertIn("DBT_DEFAULT_SCHEMA: SILVER_STAGING", self.workflow)
        self.assertIn("Render validated deployment context", self.workflow)
        self.assertIn("framework/scripts/render_dbt_context.py", self.workflow)
        self.assertIn("--workload transform", self.workflow)
        self.assertIn("--vars-file \"${RUNNER_TEMP}/esf-dbt-vars.json\"", self.workflow)

    def test_config_snapshot_registration_happens_only_after_build(self) -> None:
        build = self.workflow.index("- name: Build project")
        register = self.workflow.index("- name: Register deployed dataset configuration snapshots")
        self.assertLess(build, register)
        self.assertIn("esf_register_all_dataset_config_snapshots", self.workflow)
        self.assertIn("--vars \"$(cat \"${RUNNER_TEMP}/esf-dbt-vars.json\")\"", self.workflow)

    def test_deploy_preserves_immutable_main_history_guard(self) -> None:
        self.assertIn("merge-base --is-ancestor", self.workflow)
        self.assertIn("git -C project checkout --detach", self.workflow)
        self.assertIn("Project dbt package must pin enterprise-snowflake-data-project-framework", self.workflow)


if __name__ == "__main__":
    unittest.main()
