#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert target/config resolution in a dbt manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--materialized")
    parser.add_argument("--incremental-strategy")
    parser.add_argument("--unique-key")
    parser.add_argument("--pre-hook-contains")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    matches = [
        node
        for node in manifest.get("nodes", {}).values()
        if node.get("resource_type") == "model" and node.get("name") == args.model
    ]
    if len(matches) != 1:
        raise SystemExit(f"expected one model named {args.model!r}, found {len(matches)}")

    node = matches[0]
    actual_target = (node.get("database"), node.get("schema"))
    expected_target = (args.database, args.schema)
    if actual_target != expected_target:
        raise SystemExit(f"dbt target mismatch: expected {expected_target}, got {actual_target}")

    config = node.get("config", {})
    expected_config = {
        "materialized": args.materialized,
        "incremental_strategy": args.incremental_strategy,
        "unique_key": args.unique_key,
    }
    for key, expected in expected_config.items():
        if expected is None:
            continue
        actual = config.get(key)
        if actual != expected:
            raise SystemExit(f"dbt config mismatch for {key}: expected {expected!r}, got {actual!r}")

    if args.pre_hook_contains is not None:
        hooks = config.get("pre-hook", config.get("pre_hook", []))
        rendered = json.dumps(hooks, sort_keys=True)
        if args.pre_hook_contains.lower() not in rendered.lower():
            raise SystemExit(
                f"dbt pre-hook does not contain {args.pre_hook_contains!r}: {rendered}"
            )

    print(f"dbt manifest assertion passed: {args.database}.{args.schema}.{args.model}")


if __name__ == "__main__":
    main()
