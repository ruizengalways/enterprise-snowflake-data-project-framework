#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from enterprise_snowflake_framework.dbt_vars import build_dbt_vars


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render validated Enterprise Snowflake metadata as dbt --vars JSON.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "project_schema",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps(build_dbt_vars(args.project_root, args.schema_dir), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
