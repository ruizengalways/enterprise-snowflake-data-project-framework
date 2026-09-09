import unittest
from pathlib import Path


class ProjectDeployContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "project-deploy.yml"
        ).read_text(encoding="utf-8")

    def test_silver_sql_is_committed_not_generated(self) -> None:
        self.assertIn("silver_processing/deploy_manifest.txt", self.workflow)
        self.assertIn("Deploy committed Silver SQL in manifest order", self.workflow)
        self.assertIn("-f \"project/${path}\"", self.workflow)
        self.assertNotIn("render_dbt_vars", self.workflow)
        self.assertNotIn("render_dbt_context", self.workflow)
        self.assertNotIn("packages.yml", self.workflow)

    def test_dbt_starts_from_gold_default(self) -> None:
        self.assertIn("DBT_DEFAULT_SCHEMA: GOLD_MARTS", self.workflow)
        self.assertIn("Build Gold and Semantic models", self.workflow)
        self.assertNotIn("esf_register_all_dataset_config_snapshots", self.workflow)

    def test_deploy_preserves_immutable_main_history_guard(self) -> None:
        self.assertIn("merge-base --is-ancestor", self.workflow)
        self.assertIn("git -C project checkout --detach", self.workflow)
        self.assertIn("Validate project contracts before authentication", self.workflow)

    def test_manifest_paths_fail_closed(self) -> None:
        self.assertIn("Unsafe Silver deployment path", self.workflow)
        self.assertIn('== *".."*', self.workflow)


if __name__ == "__main__":
    unittest.main()
