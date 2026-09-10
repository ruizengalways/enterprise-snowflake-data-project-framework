import subprocess
import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.migration_cli import _build_parser, _verify_project_checkout


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

    def test_project_checkout_must_match_declared_git_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "domain"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "ci@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "CI"], check=True)
            (repo / "README.md").write_text("domain\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
            sha = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()

            self.assertEqual(repo.resolve(), _verify_project_checkout(repo, sha))
            with self.assertRaisesRegex(ValueError, "does not match"):
                _verify_project_checkout(repo, "0" * 40)


if __name__ == "__main__":
    unittest.main()
