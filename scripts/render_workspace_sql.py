#!/usr/bin/env python3
from __future__ import annotations

import argparse

from enterprise_snowflake_framework.workspaces import (
    STANDARD_LAYERS,
    normalize_token,
    personal_schema_names,
    pr_schema_names,
    render_create_schema_sql,
    render_drop_schema_sql,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render guarded Snowflake workspace lifecycle SQL.")
    parser.add_argument("--kind", choices=("personal", "pr"), required=True)
    parser.add_argument("--action", choices=("create", "drop"), required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--developer")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--layers", nargs="+", default=list(STANDARD_LAYERS))
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.kind == "personal":
        if not args.developer or args.pr_number is not None:
            raise SystemExit("personal workspace requires --developer and must not set --pr-number")
        schemas = personal_schema_names(args.developer, args.layers)
        if args.action == "create":
            sql = render_create_schema_sql(args.database, schemas, transient=False, retention_days=1)
        else:
            sql = render_drop_schema_sql(
                args.database,
                schemas,
                required_prefix=f"{normalize_token(args.developer)}_",
            )
    else:
        if args.pr_number is None or args.developer:
            raise SystemExit("PR workspace requires --pr-number and must not set --developer")
        schemas = pr_schema_names(args.pr_number, args.layers)
        if args.action == "create":
            sql = render_create_schema_sql(args.database, schemas, transient=True, retention_days=0)
        else:
            sql = render_drop_schema_sql(
                args.database,
                schemas,
                required_prefix=f"PR_{args.pr_number}_",
            )

    print(sql)


if __name__ == "__main__":
    main()
