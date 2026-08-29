#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from enterprise_snowflake_framework.targets import resolve_dbt_target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve canonical Snowflake/dbt target metadata.")
    parser.add_argument("--project-code", required=True)
    parser.add_argument("--environment", required=True, choices=["dev", "ci", "uat", "prod"])
    parser.add_argument("--workload", required=True, choices=["query", "transform", "ci"])
    parser.add_argument("--developer")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--default-schema", default="STAGING")
    parser.add_argument("--format", choices=["json", "env"], default="json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target = resolve_dbt_target(
        args.project_code,
        args.environment,
        args.workload,
        developer=args.developer,
        pr_number=args.pr_number,
        default_schema=args.default_schema,
    )
    if args.format == "json":
        print(json.dumps(target.as_dict(), sort_keys=True))
        return
    for key, value in target.as_env().items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
