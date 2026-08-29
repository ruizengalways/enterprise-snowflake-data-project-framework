import json
import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.dbt_context import (
    build_dbt_execution_context,
    write_env_file,
    write_vars_file,
)


class DbtExecutionContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.project_root = self.repo_root / "examples" / "minimal-project"
        self.schema_dir = self.repo_root / "project_schema"

    def test_ci_context_combines_target_run_tag_and_dataset_tags(self) -> None:
        context = build_dbt_execution_context(
            self.project_root,
            self.schema_dir,
            "HEALTH",
            "ci",
            "ci",
            pr_number=77,
            run_id="run-77",
            git_sha="deadbeef",
        )

        self.assertEqual(context.env["DBT_DATABASE"], "CI_HEALTH")
        self.assertEqual(context.env["DBT_WAREHOUSE"], "WH_HEALTH_CI")
        self.assertEqual(context.env["ESF_SCHEMA_PREFIX"], "PR_77")

        run_tag = json.loads(context.env["DBT_QUERY_TAG"])
        self.assertEqual(run_tag["project"], "health")
        self.assertEqual(run_tag["operation"], "dbt_run")
        self.assertEqual(run_tag["pr_number"], 77)

        dataset_tag = json.loads(context.dbt_vars["esf_datasets"]["patient"]["query_tag"])
        self.assertEqual(dataset_tag["dataset"], "patient")
        self.assertEqual(dataset_tag["source"], "ehr_mssql")
        self.assertEqual(dataset_tag["operation"], "dbt_model")

    def test_project_code_must_match_metadata(self) -> None:
        with self.assertRaises(ValueError):
            build_dbt_execution_context(
                self.project_root,
                self.schema_dir,
                "TRANSPORT",
                "ci",
                "ci",
                pr_number=1,
            )

    def test_files_are_machine_consumable(self) -> None:
        context = build_dbt_execution_context(
            self.project_root,
            self.schema_dir,
            "HEALTH",
            "dev",
            "transform",
            developer="alice.smith",
            run_id="local-run",
        )
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "env"
            vars_path = Path(tmp) / "vars.json"
            write_env_file(env_path, context.env)
            write_vars_file(vars_path, context.dbt_vars)
            self.assertIn("DBT_QUERY_TAG=", env_path.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(vars_path.read_text(encoding="utf-8"))["esf_project"]["code"], "HEALTH")


if __name__ == "__main__":
    unittest.main()
