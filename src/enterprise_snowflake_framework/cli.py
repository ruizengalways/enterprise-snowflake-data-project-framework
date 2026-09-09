from __future__ import annotations

import argparse
from pathlib import Path

from .init_project import initialize_project
from .plan import SourcePlan, build_source_plan
from .scaffold import SUPPORTED_PATTERNS, scaffold_all, scaffold_pipeline
from .source_management import add_source
from .validation import validate_project_tree


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esf",
        description=(
            "Enterprise Snowflake Data Project Toolkit. It creates and validates readable, "
            "domain-owned source code; it is not a runtime engine."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_project = subparsers.add_parser("init-project", help="Initialize a domain repository without overwriting existing files.")
    init_project.add_argument("--project-root", type=Path, default=Path.cwd())

    add_source_parser = subparsers.add_parser("add-source", help="Add one source-system boundary to an initialized project.")
    add_source_parser.add_argument("source_id")
    add_source_parser.add_argument("--project-root", type=Path, default=Path.cwd())

    plan = subparsers.add_parser("plan", help="Show append-only scaffold actions without writing files.")
    plan.add_argument("--source", required=True, dest="source_id")
    plan.add_argument("--project-root", type=Path, default=Path.cwd())

    scaffold = subparsers.add_parser("scaffold", help="Create one new domain-owned Silver dataset directory.")
    scaffold.add_argument("pattern", choices=sorted(SUPPORTED_PATTERNS))
    scaffold.add_argument("dataset_id")
    scaffold.add_argument("--source", required=True, dest="source_id")
    scaffold.add_argument("--project-root", type=Path, default=Path.cwd())

    scaffold_all_parser = subparsers.add_parser("scaffold-all", help="Create only missing dataset directories declared by one source manifest.")
    scaffold_all_parser.add_argument("--source", required=True, dest="source_id")
    scaffold_all_parser.add_argument("--project-root", type=Path, default=Path.cwd())

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
            print(f"    WARNING: existing dataset directory does not match standard scaffold layout; missing: {missing}. No files changed.")
    if plan.existing:
        print(f"  {len(plan.existing)} total")
    else:
        print("  0")
    print()
    print("WILL CREATE")
    for item in plan.new:
        print(f"  {item.dataset_id:<24} {item.pattern}")
    if plan.new:
        print(f"  {len(plan.new)} total")
    else:
        print("  0")
    print()
    print("WILL OVERWRITE")
    print("  0")


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
            if result.created:
                print(f"Added source: {result.source_id}")
            else:
                print(f"Source already exists: {result.source_id}. No files changed.")
            return

        if args.command == "plan":
            _print_plan(build_source_plan(args.project_root, args.source_id))
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
                    print(
                        f"WARNING: {item.destination} does not match standard scaffold layout. No files changed."
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
