from __future__ import annotations

import json
from collections.abc import Mapping

MAX_QUERY_TAG_LENGTH = 2000
REQUIRED_KEYS = ("project", "environment", "workload")
ALLOWED_KEYS = {
    "project",
    "environment",
    "workload",
    "source",
    "pipeline",
    "dataset",
    "run_id",
    "git_sha",
    "pr_number",
    "operation",
}


def build_query_tag(metadata: Mapping[str, object]) -> str:
    """Return a deterministic compact JSON Snowflake QUERY_TAG.

    Values are operational identifiers only. Do not place personal, sensitive,
    regulated, or free-form business data into query-tag metadata.
    """
    unknown = sorted(set(metadata) - ALLOWED_KEYS)
    if unknown:
        raise ValueError(f"unsupported query-tag keys: {', '.join(unknown)}")

    missing = [key for key in REQUIRED_KEYS if metadata.get(key) in (None, "")]
    if missing:
        raise ValueError(f"missing required query-tag keys: {', '.join(missing)}")

    normalized: dict[str, str | int | bool] = {}
    for key, raw_value in metadata.items():
        if raw_value is None or raw_value == "":
            continue
        if isinstance(raw_value, bool):
            normalized[key] = raw_value
        elif isinstance(raw_value, int):
            normalized[key] = raw_value
        elif isinstance(raw_value, str):
            normalized[key] = raw_value.strip()
        else:
            raise ValueError(f"query-tag value for {key} must be string, integer, boolean, or null")

    result = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(result) > MAX_QUERY_TAG_LENGTH:
        raise ValueError(
            f"query tag is {len(result)} characters; Snowflake QUERY_TAG limit is {MAX_QUERY_TAG_LENGTH}"
        )
    return result


def render_set_query_tag_sql(metadata: Mapping[str, object]) -> str:
    """Render a single guarded ALTER SESSION statement for QUERY_TAG."""
    tag = build_query_tag(metadata)
    escaped = tag.replace("'", "''")
    return f"ALTER SESSION SET QUERY_TAG = '{escaped}';"
