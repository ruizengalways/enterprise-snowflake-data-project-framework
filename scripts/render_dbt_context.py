#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from enterprise_snowflake_framework.dbt_context import (
    build_dbt_execution_context,
    write_env_file,
    write_vars_file,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve dbt target, canonical QUERY_TAG metadata, and validated dbt vars together."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--project-code", required=True)
    parser.add_argument("--environment", required=True, choices=["dev", "ci", "uat", "prod"])
    parser.add_argument("--workload", required=True, choices=["query", "transform", "ci"])
    parser.add_argument("--developer")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--run-id")
    parser.add_argument("--git-sha")
    parser.add_argument("--default-schema", default="STAGING")
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "project_schema",
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--vars-file", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    context = build_dbt_execution_context(
        args.project_root,
        args.schema_dir,
        args.project_code,
        args.environment,
        args.workload,
        developer=args.developer,
        pr_number=args.pr_number,
        run_id=args.run_id,
        git_sha=args.git_sha,
        default_schema=args.default_schema,
    )

    if args.env_file:
        write_env_file(args.env_file, context.env)
    if args.vars_file:
        write_vars_file(args.vars_file, context.dbt_vars)

    if not args.env_file and not args.vars_file:
        print(json.dumps(context.as_dict(), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
