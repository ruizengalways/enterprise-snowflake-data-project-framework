import unittest
from pathlib import Path

from enterprise_snowflake_framework.migration_cli import _build_parser


class MigrationCliContractTests(unittest.TestCase):
    def test_deploy_parser_requires_immutable_git_shas(self) -> None:
        args = _build_parser().parse_args(
            [
                "deploy",
                "--project-root",
                ".",
                "--project-git-sha",
                "1" * 40,
                "--framework-git-sha",
                "2" * 40,
            ]
        )
        self.assertEqual("deploy", args.command)
        self.assertEqual("1" * 40, args.project_git_sha)
        self.assertEqual("2" * 40, args.framework_git_sha)

    def test_baseline_requires_explicit_confirmation_flag_in_interface(self) -> None:
        args = _build_parser().parse_args(
            [
                "baseline",
                "--project-git-sha",
                "1" * 40,
                "--framework-git-sha",
                "2" * 40,
                "--reason",
                "reviewed",
            ]
        )
        self.assertFalse(args.confirm_existing_state_reviewed)

    def test_resolve_requires_explicit_partial_state_confirmation_flag(self) -> None:
        args = _build_parser().parse_args(
            [
                "resolve",
                "silver_processing/source/customer/090_fix.sql",
                "--project-git-sha",
                "1" * 40,
                "--framework-git-sha",
                "2" * 40,
                "--reason",
                "reviewed",
            ]
        )
        self.assertFalse(args.confirm_partial_state_reviewed)

    def test_console_entrypoint_is_packaged(self) -> None:
        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('esf-migrate = "enterprise_snowflake_framework.migration_cli:main"', pyproject)


if __name__ == "__main__":
    unittest.main()
