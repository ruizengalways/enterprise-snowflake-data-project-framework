from __future__ import annotations

import argparse
from pathlib import Path

from .control_plan import build_control_plan
from .dataset_management import add_dataset
from .init_project import initialize_project
from .lifecycle import LIFECYCLE_ACTIONS, generate_lifecycle_scripts
from .plan import SourcePlan, build_source_plan
from .repair import PROBLEM_LAYERS, build_repair_plan, generate_silver_repair_scripts
from .scaffold import (
    SUPPORTED_PATTERNS,
    scaffold_all,
    scaffold_pipeline,
    scaffold_preview,
)
from .sla_policy import CADENCE_TYPES, SLA_STAGES, generate_sla_sql
from .source_management import add_source
from .validation import validate_project_tree
from .versioning import generate_release_scripts, scaffold_version


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esf",
        description=(
            "Enterprise Snowflake Data Project Toolkit. It creates and validates readable, "
            "domain-owned source code; it is not a runtime engine."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_project = subparsers.add_parser(
        "init-project", help="Initialize a domain repository without overwriting existing files."
    )
    init_project.add_argument("--project-root", type=Path, default=Path.cwd())

    add_source_parser = subparsers.add_parser(
        "add-source", help="Add one source-system boundary to an initialized project."
    )
    add_source_parser.add_argument("source_id")
    add_source_parser.add_argument("--project-root", type=Path, default=Path.cwd())

    add_dataset_parser = subparsers.add_parser(
        "add-dataset",
        help="Append one dataset declaration to a source manifest without scaffolding SQL.",
    )
    add_dataset_parser.add_argument("dataset_id")
    add_dataset_parser.add_argument("--source", required=True, dest="source_id")
    add_dataset_parser.add_argument("--pattern", required=True, choices=sorted(SUPPORTED_PATTERNS))
    add_dataset_parser.add_argument(
        "--raw-contract",
        help="Project-relative RAW contract path; defaults to contracts/raw/<source>/<dataset>.yml.",
    )
    add_dataset_parser.add_argument("--project-root", type=Path, default=Path.cwd())

    plan = subparsers.add_parser("plan", help="Show append-only scaffold actions without writing files.")
    plan.add_argument("--source", required=True, dest="source_id")
    plan.add_argument("--project-root", type=Path, default=Path.cwd())

    control_plan = subparsers.add_parser(
        "control-plan",
        help="Show domain control-plane upgrade/deploy-manifest gaps without modifying the repository.",
    )
    control_plan.add_argument("--project-root", type=Path, default=Path.cwd())

    preview = subparsers.add_parser(
        "scaffold-preview", help="Render a new dataset starter in memory without writing files."
    )
    preview.add_argument("dataset_id")
    preview.add_argument("--source", required=True, dest="source_id")
    preview.add_argument("--show-content", action="store_true")
    preview.add_argument("--project-root", type=Path, default=Path.cwd())

    scaffold = subparsers.add_parser(
        "scaffold", help="Create one new domain-owned Silver dataset directory."
    )
    scaffold.add_argument("pattern", choices=sorted(SUPPORTED_PATTERNS))
    scaffold.add_argument("dataset_id")
    scaffold.add_argument("--source", required=True, dest="source_id")
    scaffold.add_argument("--project-root", type=Path, default=Path.cwd())

    scaffold_all_parser = subparsers.add_parser(
        "scaffold-all", help="Create only missing dataset directories declared by one source manifest."
    )
    scaffold_all_parser.add_argument("--source", required=True, dest="source_id")
    scaffold_all_parser.add_argument("--project-root", type=Path, default=Path.cwd())

    scaffold_version_parser = subparsers.add_parser(
        "scaffold-version",
        help="Create a new candidate implementation under an existing dataset without modifying active code.",
    )
    scaffold_version_parser.add_argument("dataset_id")
    scaffold_version_parser.add_argument("version")
    scaffold_version_parser.add_argument("--source", required=True, dest="source_id")
    scaffold_version_parser.add_argument("--project-root", type=Path, default=Path.cwd())

    sla_sql = subparsers.add_parser(
        "sla-sql",
        help="Generate an explicit logical-dataset SLA policy revision for review; never execute it.",
    )
    sla_sql.add_argument("dataset_id")
    sla_sql.add_argument("policy_id")
    sla_sql.add_argument("--source", required=True, dest="source_id")
    sla_sql.add_argument("--stage", required=True, type=str.upper, choices=sorted(SLA_STAGES))
    sla_sql.add_argument("--cadence", required=True, type=str.upper, choices=sorted(CADENCE_TYPES))
    sla_sql.add_argument("--max-latency-seconds", type=int)
    sla_sql.add_argument("--max-freshness-seconds", type=int)
    sla_sql.add_argument("--expected-interval-seconds", type=int)
    sla_sql.add_argument("--deadline-local-time")
    sla_sql.add_argument("--timezone")
    sla_sql.add_argument("--disabled", action="store_true")
    sla_sql.add_argument("--output-root", type=Path)
    sla_sql.add_argument("--project-root", type=Path, default=Path.cwd())

    lifecycle_sql = subparsers.add_parser(
        "lifecycle-sql",
        help="Generate explicit pause/resume/soft-decommission SQL for engineer review; never execute it.",
    )
    lifecycle_sql.add_argument("dataset_id")
    lifecycle_sql.add_argument("operation_id")
    lifecycle_sql.add_argument("--source", required=True, dest="source_id")
    lifecycle_sql.add_argument("--action", required=True, choices=sorted(LIFECYCLE_ACTIONS))
    lifecycle_sql.add_argument("--version")
    lifecycle_sql.add_argument("--output-root", type=Path)
    lifecycle_sql.add_argument("--project-root", type=Path, default=Path.cwd())

    repair_plan = subparsers.add_parser(
        "repair-plan", help="Explain the repair path without writing files or executing Snowflake SQL."
    )
    repair_plan.add_argument("dataset_id")
    repair_plan.add_argument("--source", required=True, dest="source_id")
    repair_plan.add_argument("--problem", required=True, choices=sorted(PROBLEM_LAYERS))
    repair_plan.add_argument("--from", dest="requested_from")
    repair_plan.add_argument("--to", dest="requested_to")
    repair_plan.add_argument("--project-root", type=Path, default=Path.cwd())

    repair_sql = subparsers.add_parser(
        "repair-sql", help="Generate explicit candidate replay SQL for engineer review; never execute it."
    )
    repair_sql.add_argument("dataset_id")
    repair_sql.add_argument("version")
    repair_sql.add_argument("--source", required=True, dest="source_id")
    repair_sql.add_argument("--from", dest="requested_from")
    repair_sql.add_argument("--to", dest="requested_to")
    repair_sql.add_argument("--output-root", type=Path)
    repair_sql.add_argument("--project-root", type=Path, default=Path.cwd())

    release_sql = subparsers.add_parser(
        "release-sql", help="Generate explicit activate/rollback SQL; never execute it."
    )
    release_sql.add_argument("dataset_id")
    release_sql.add_argument("--source", required=True, dest="source_id")
    release_sql.add_argument("--from-version", required=True)
    release_sql.add_argument("--to-version", required=True)
    release_sql.add_argument("--output-root", type=Path)
    release_sql.add_argument("--project-root", type=Path, default=Path.cwd())

    validate = subparsers.add_parser("validate", help="Validate project, source, RAW, and Silver contracts.")
    validate.add_argument("--project-root", type=Path, default=Path.cwd())
    return parser


def _print_plan(plan: SourcePlan) -> None:
    print(f"Source: {plan.source_id}")
    print()
    print(f"Manifest datasets: {plan.manifest_count}")
    print(f"Existing pipelines: {len(plan.existing)}")
    print(f"New pipelines: {len(plan.new)}")
    print()
    print("SKIPPED / DOMAIN OWNED")
    for item in plan.existing:
        print(f"  {item.dataset_id:<24} {item.pattern}")
        if item.missing_standard_files:
            missing = ", ".join(item.missing_standard_files)
            print(
                "    WARNING: existing dataset directory does not match standard scaffold layout; "
                f"missing: {missing}. No files changed."
            )
    print(f"  {len(plan.existing)} total" if plan.existing else "  0")
    print()
    print("WILL CREATE")
    for item in plan.new:
        print(f"  {item.dataset_id:<24} {item.pattern}")
    print(f"  {len(plan.new)} total" if plan.new else "  0")
    print()
    print("WILL OVERWRITE")
    print("  0")


def _print_control_plan(project_root: Path) -> None:
    plan = build_control_plan(project_root)
    print(f"Control manifest: {plan.manifest}")
    print(f"Ready: {'YES' if plan.ready else 'NO'}")
    print()
    print("KNOWN FILES PRESENT")
    for path in plan.known_files_present:
        print(f"  {path}")
    if not plan.known_files_present:
        print("  0")
    print()
    print("MISSING FROM REPO")
    for path in plan.known_files_missing:
        print(f"  {path}")
    if not plan.known_files_missing:
        print("  0")
    print()
    print("MISSING FROM DEPLOY MANIFEST")
    for path in plan.missing_from_manifest:
        print(f"  {path}")
    if not plan.missing_from_manifest:
        print("  0")
    print()
    print("DOMAIN-OWNED / UNKNOWN MANIFEST ENTRIES")
    for path in plan.unknown_manifest_entries:
        print(f"  {path}")
    if not plan.unknown_manifest_entries:
        print("  0")
    print()
    print("No files changed.")


def main() -> None:
    args = _build_parser().parse_args()
    try:
        if args.command == "init-project":
            result = initialize_project(args.project_root)
            print(f"Project root: {result.project_root}")
            print(f"Created files: {len(result.created_files)}")
            print(f"Existing files left unchanged: {len(result.skipped_files)}")
            return

        if args.command == "add-source":
            result = add_source(args.project_root, args.source_id)
            print(
                f"Added source: {result.source_id}"
                if result.created
                else f"Source already exists: {result.source_id}. No files changed."
            )
            return

        if args.command == "add-dataset":
            result = add_dataset(
                project_root=args.project_root,
                source_id=args.source_id,
                dataset_id=args.dataset_id,
                pattern=args.pattern,
                raw_contract=args.raw_contract,
            )
            if result.created:
                print(
                    f"Added dataset: {result.source_id}.{result.dataset_id} "
                    f"({result.pattern}) -> {result.raw_contract}"
                )
                print("No Silver files were scaffolded. Run `esf plan` or `esf scaffold-preview` next.")
            else:
                print(
                    f"Dataset already exists: {result.source_id}.{result.dataset_id}. "
                    "No files changed."
                )
            return

        if args.command == "plan":
            _print_plan(build_source_plan(args.project_root, args.source_id))
            return

        if args.command == "control-plan":
            _print_control_plan(args.project_root)
            return

        if args.command == "scaffold-preview":
            result = scaffold_preview(
                project_root=args.project_root,
                source_id=args.source_id,
                dataset_id=args.dataset_id,
            )
            print(f"Dataset: {result.source_id}.{result.dataset_id}")
            print(f"Destination: {result.destination}")
            if result.domain_owned:
                print("DOMAIN OWNED: existing directory will not be modified.")
                print("WILL CREATE: 0")
                print("WILL OVERWRITE: 0")
                return
            print(f"WILL CREATE: {len(result.files)}")
            for filename in result.files:
                print(f"  {filename}")
            print("WILL OVERWRITE: 0")
            if args.show_content:
                for filename in result.files:
                    print(f"\n===== {filename} =====")
                    print(result.rendered[filename], end="")
            return

        if args.command == "scaffold":
            result = scaffold_pipeline(
                project_root=args.project_root,
                source_id=args.source_id,
                pattern=args.pattern,
                dataset_id=args.dataset_id,
            )
            if result.created:
                print(f"Created: {result.destination}")
            else:
                print(f"SKIPPED / DOMAIN OWNED: {result.destination}")
                if result.missing_standard_files:
                    print("WARNING: existing dataset directory does not match standard scaffold layout. No files changed.")
            return

        if args.command == "scaffold-all":
            result = scaffold_all(project_root=args.project_root, source_id=args.source_id)
            print(f"Source: {result.source_id}")
            print(f"Created: {len(result.created)}")
            print(f"Skipped / domain owned: {len(result.skipped)}")
            print(f"Overwritten: {result.overwritten}")
            for item in result.skipped:
                if item.missing_standard_files:
                    print(f"WARNING: {item.destination} does not match standard scaffold layout. No files changed.")
            return

        if args.command == "scaffold-version":
            result = scaffold_version(
                project_root=args.project_root,
                source_id=args.source_id,
                dataset_id=args.dataset_id,
                version=args.version,
            )
            print(
                f"Created candidate: {result.destination}"
                if result.created
                else f"SKIPPED / VERSION OWNED: {result.destination}. No files changed."
            )
            return

        if args.command == "sla-sql":
            result = generate_sla_sql(
                project_root=args.project_root,
                source_id=args.source_id,
                dataset_id=args.dataset_id,
                policy_id=args.policy_id,
                stage=args.stage,
                cadence_type=args.cadence,
                max_latency_seconds=args.max_latency_seconds,
                max_freshness_seconds=args.max_freshness_seconds,
                expected_interval_seconds=args.expected_interval_seconds,
                deadline_local_time=args.deadline_local_time,
                timezone=args.timezone,
                enabled=not args.disabled,
                output_root=args.output_root,
            )
            print(
                f"Generated SLA policy SQL: {result.destination}"
                if result.created
                else f"SKIPPED / SLA POLICY OWNED: {result.destination}. No files changed."
            )
            return

        if args.command == "lifecycle-sql":
            result = generate_lifecycle_scripts(
                project_root=args.project_root,
                source_id=args.source_id,
                dataset_id=args.dataset_id,
                action=args.action,
                operation_id=args.operation_id,
                version=args.version,
                output_root=args.output_root,
            )
            print(
                f"Generated lifecycle scripts: {result.destination}"
                if result.created
                else f"SKIPPED / LIFECYCLE OWNED: {result.destination}. No files changed."
            )
            return

        if args.command == "repair-plan":
            result = build_repair_plan(
                project_root=args.project_root,
                source_id=args.source_id,
                dataset_id=args.dataset_id,
                problem=args.problem,
                requested_from=args.requested_from,
                requested_to=args.requested_to,
            )
            print(result.render(), end="")
            return

        if args.command == "repair-sql":
            result = generate_silver_repair_scripts(
                project_root=args.project_root,
                source_id=args.source_id,
                dataset_id=args.dataset_id,
                candidate_version=args.version,
                requested_from=args.requested_from,
                requested_to=args.requested_to,
                output_root=args.output_root,
            )
            print(
                f"Generated repair scripts: {result.destination}"
                if result.created
                else f"SKIPPED / REPAIR OWNED: {result.destination}. No files changed."
            )
            return

        if args.command == "release-sql":
            result = generate_release_scripts(
                project_root=args.project_root,
                source_id=args.source_id,
                dataset_id=args.dataset_id,
                from_version=args.from_version,
                to_version=args.to_version,
                output_root=args.output_root,
            )
            print(
                f"Generated release scripts: {result.destination}"
                if result.created
                else f"SKIPPED / RELEASE OWNED: {result.destination}. No files changed."
            )
            return

        errors = validate_project_tree(args.project_root)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            raise SystemExit(1)
        print(f"Contract validation passed: {args.project_root}")
    except (FileNotFoundError, FileExistsError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
