from __future__ import annotations

import argparse
from pathlib import Path

from .metadata_validation import validate_project_tree
from .scaffold import SUPPORTED_PATTERNS, scaffold_pipeline


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esf",
        description="Enterprise Snowflake project toolkit. It validates contracts and scaffolds readable domain-owned SQL; it is not a runtime engine.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate project, RAW, and Silver pipeline contracts.")
    validate.add_argument("--project-root", type=Path, required=True)

    scaffold = subparsers.add_parser("scaffold", help="Copy a readable Silver pattern into the domain repository.")
    scaffold.add_argument("pattern", choices=sorted(SUPPORTED_PATTERNS))
    scaffold.add_argument("dataset_id")
    scaffold.add_argument("--raw-contract", required=True)
    scaffold.add_argument("--project-root", type=Path, default=Path.cwd())
    scaffold.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.command == "validate":
        errors = validate_project_tree(args.project_root)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            raise SystemExit(1)
        print(f"Contract validation passed: {args.project_root}")
        return

    destination = scaffold_pipeline(
        project_root=args.project_root,
        pattern=args.pattern,
        dataset_id=args.dataset_id,
        raw_contract=args.raw_contract,
        force=args.force,
    )
    print(destination)


if __name__ == "__main__":
    main()
