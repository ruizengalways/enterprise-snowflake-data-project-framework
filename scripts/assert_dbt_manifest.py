#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert database/schema resolution in a dbt manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--schema", required=True)
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
    actual = (node.get("database"), node.get("schema"))
    expected = (args.database, args.schema)
    if actual != expected:
        raise SystemExit(f"dbt target mismatch: expected {expected}, got {actual}")
    print(f"dbt target assertion passed: {args.database}.{args.schema}.{args.model}")


if __name__ == "__main__":
    main()
