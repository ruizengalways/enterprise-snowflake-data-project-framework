#!/usr/bin/env python3
from __future__ import annotations

import argparse

from enterprise_snowflake_framework.query_tags import build_query_tag, render_set_query_tag_sql


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render canonical Snowflake QUERY_TAG metadata.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--workload", required=True)
    parser.add_argument("--source")
    parser.add_argument("--pipeline")
    parser.add_argument("--dataset")
    parser.add_argument("--run-id")
    parser.add_argument("--git-sha")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--operation")
    parser.add_argument("--as-sql", action="store_true", help="Render ALTER SESSION SET QUERY_TAG SQL")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metadata = {
        "project": args.project,
        "environment": args.environment,
        "workload": args.workload,
        "source": args.source,
        "pipeline": args.pipeline,
        "dataset": args.dataset,
        "run_id": args.run_id,
        "git_sha": args.git_sha,
        "pr_number": args.pr_number,
        "operation": args.operation,
    }
    print(render_set_query_tag_sql(metadata) if args.as_sql else build_query_tag(metadata))


if __name__ == "__main__":
    main()
