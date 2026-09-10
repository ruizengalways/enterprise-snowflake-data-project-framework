from __future__ import annotations

import argparse
import tempfile
from importlib.metadata import version
from pathlib import Path

from enterprise_snowflake_framework.certification_snowflake import (
    SnowflakeCertifier,
    _required_environment,
    cleanup_certification_schemas,
)
from enterprise_snowflake_framework.migration_snowflake import SnowCliClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the trusted real-Snowflake certification suite against the dedicated "
            "CI_FRAMEWORK_CERT database. This command is not intended for untrusted PR execution."
        )
    )
    parser.add_argument("--framework-git-sha", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Drop certification schemas only. Used by the workflow's always-run cleanup step.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if len(args.framework_git_sha) != 40 or any(ch not in "0123456789abcdef" for ch in args.framework_git_sha):
        raise SystemExit("--framework-git-sha must be a lowercase 40-character Git SHA")

    client = SnowCliClient()
    _required_environment(client.env)
    if args.cleanup_only:
        cleanup_certification_schemas(client)
        print("Snowflake certification schemas cleaned.")
        return

    with tempfile.TemporaryDirectory() as tmp:
        project_root = Path(tmp) / "enterprise-snowflake-framework-cert-analytics"
        certifier = SnowflakeCertifier(
            client=client,
            framework_git_sha=args.framework_git_sha,
            framework_version=version("enterprise-snowflake-data-project-framework"),
            fixture_path=args.fixture,
            workspace_root=project_root,
            output_dir=args.output_dir,
        )
        report = certifier.run()
        print(f"Snowflake certification status: {report.status}")
        for name, status in sorted(report.checks.items()):
            print(f"  {name}: {status}")


if __name__ == "__main__":
    main()
