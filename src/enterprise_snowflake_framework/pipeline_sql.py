from __future__ import annotations

from typing import Any

from .pipeline_apply import render_apply_sql as _render_apply_sql
from .pipeline_compare import render_compare_sql
from .pipeline_model import PipelineNames, build_names
from .pipeline_objects import render_objects_sql, render_validate_sql
from .pipeline_operations import (
    render_deploy_fragment,
    render_publish_sql,
    render_register_sql,
    render_release_sql,
    render_task_sql,
    render_version_yaml,
)
from .pipeline_policy import render_policy_sql
from .pipeline_replay import render_replay_sql as _render_replay_sql


def _create_only_persistent_procedure(sql: str) -> str:
    """Make the one persistent procedure in a generated migration create-only.

    Apply/replay renderers also contain Snowflake procedure-scoped temporary tables whose
    CREATE OR REPLACE semantics are intentional per invocation. Only the first persistent
    SILVER procedure declaration is hardened here.
    """
    marker = "CREATE OR REPLACE PROCEDURE SILVER."
    if marker not in sql:
        return sql
    return sql.replace(marker, "CREATE PROCEDURE SILVER.", 1)


def render_apply_sql(pattern: str, names: PipelineNames, contract: dict[str, Any]) -> str:
    return _create_only_persistent_procedure(_render_apply_sql(pattern, names, contract))


def render_replay_sql(pattern: str, names: PipelineNames, contract: dict[str, Any]) -> str:
    return _create_only_persistent_procedure(_render_replay_sql(pattern, names, contract))


__all__ = [
    "PipelineNames",
    "build_names",
    "render_apply_sql",
    "render_compare_sql",
    "render_deploy_fragment",
    "render_objects_sql",
    "render_policy_sql",
    "render_publish_sql",
    "render_register_sql",
    "render_release_sql",
    "render_replay_sql",
    "render_task_sql",
    "render_validate_sql",
    "render_version_yaml",
]
