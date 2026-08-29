#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from enterprise_snowflake_framework.metadata_validation import validate_project_tree


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an Enterprise Snowflake data-project metadata tree.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "project_schema",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    errors = validate_project_tree(args.project_root, args.schema_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print(f"Metadata validation passed: {args.project_root}")


if __name__ == "__main__":
    main()
