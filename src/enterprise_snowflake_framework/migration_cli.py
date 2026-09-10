from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from .migration_deployment import (
    DeploymentIdentity,
    MigrationBlocked,
    MigrationError,
    SnowCliClient,
    SnowflakeHistoryStore,
    baseline_existing_migrations,
    deploy_migrations,
    remediate_migration,
)


def _identity(args: argparse.Namespace) -> DeploymentIdentity:
    return DeploymentIdentity(
        project_git_sha=args.project_git_sha,
        framework_git_sha=args.framework_git_sha,
        github_run_id=args.github_run_id,
    )


def _add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-git-sha", required=True)
    parser.add_argument("--framework-git-sha", required=True)
    parser.add_argument("--github-run-id", default=os.environ.get("GITHUB_RUN_ID"))


def _verify_project_checkout(project_root: Path, expected_sha: str) -> Path:
    project_root = project_root.resolve()
    completed = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"project root is not a readable Git checkout: {project_root}")
    actual = completed.stdout.strip()
    if actual != expected_sha:
        raise ValueError(
            f"project checkout SHA does not match --project-git-sha: expected {expected_sha}, got {actual}"
        )
    return project_root


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esf-migrate",
        description=(
            "Apply committed CONTROL and SILVER SQL once per environment using a checksum-locked "
            "domain-local deployment history. It never scaffolds or generates runtime SQL."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy = subparsers.add_parser(
        "deploy",
        help="Apply only new migrations; skip identical applied files and block drift/partial attempts.",
    )
    deploy.add_argument("--project-root", type=Path, default=Path.cwd())
    _add_identity_arguments(deploy)

    baseline = subparsers.add_parser(
        "baseline",
        help="Adopt an existing populated domain without re-executing historical manifest files.",
    )
    baseline.add_argument("--project-root", type=Path, default=Path.cwd())
    _add_identity_arguments(baseline)
    baseline.add_argument("--reason", required=True)
    baseline.add_argument("--confirm-existing-state-reviewed", action="store_true")

    resolve = subparsers.add_parser(
        "resolve",
        help=(
            "Mark one unresolved STARTED/FAILED migration as REMEDIATED after explicit review of "
            "partial Snowflake state; the file itself is not re-executed."
        ),
    )
    resolve.add_argument("migration_path")
    resolve.add_argument("--project-root", type=Path, default=Path.cwd())
    _add_identity_arguments(resolve)
    resolve.add_argument("--reason", required=True)
    resolve.add_argument("--confirm-partial-state-reviewed", action="store_true")

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        identity = _identity(args)
        identity.validate()
        project_root = _verify_project_checkout(args.project_root, identity.project_git_sha)

        selected_framework_sha = os.environ.get("ESF_FRAMEWORK_GIT_SHA")
        if selected_framework_sha and selected_framework_sha != identity.framework_git_sha:
            raise ValueError(
                "--framework-git-sha does not match ESF_FRAMEWORK_GIT_SHA selected by the deployment workflow"
            )

        client = SnowCliClient()
        store = SnowflakeHistoryStore(client)

        if args.command == "deploy":
            result = deploy_migrations(project_root, identity, store, client)
            print("Apply-once migration deployment complete.")
            print(f"Applied: {len(result.applied)}")
            for path in result.applied:
                print(f"  APPLY {path}")
            print(f"Skipped: {len(result.skipped)}")
            for path in result.skipped:
                print(f"  SKIP  {path}")
            return

        if args.command == "baseline":
            paths = baseline_existing_migrations(
                project_root,
                identity,
                store,
                reason=args.reason,
                confirmed=args.confirm_existing_state_reviewed,
            )
            print("Existing domain migration baseline recorded. No migration files were executed.")
            print(f"Baselined: {len(paths)}")
            for path in paths:
                print(f"  BASELINE {path}")
            return

        if args.command == "resolve":
            path = remediate_migration(
                project_root,
                identity,
                store,
                migration_path=args.migration_path,
                reason=args.reason,
                confirmed=args.confirm_partial_state_reviewed,
            )
            print(f"Recorded explicit remediation for: {path}")
            print("The migration file was not re-executed.")
            return

        raise AssertionError(f"unsupported command: {args.command}")
    except MigrationBlocked as exc:
        print("Migration deployment BLOCKED.")
        for error in exc.errors:
            print(f"  - {error}")
        raise SystemExit(2) from exc
    except ValueError as exc:
        print(f"Migration input error: {exc}")
        raise SystemExit(2) from exc
    except MigrationError as exc:
        print(f"Migration execution failed: {exc}")
        raise SystemExit(5) from exc


if __name__ == "__main__":
    main()
