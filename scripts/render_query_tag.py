#!/usr/bin/env python3
from __future__ import annotations

import argparse

from enterprise_snowflake_framework.query_tags import build_query_tag


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a canonical compact JSON Snowflake QUERY_TAG.")
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(
        build_query_tag(
            {
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
        )
    )


if __name__ == "__main__":
    main()
