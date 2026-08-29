from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .dbt_vars import build_dbt_vars
from .metadata_validation import load_document
from .query_tags import build_query_tag
from .targets import DbtTarget, resolve_dbt_target


@dataclass(frozen=True)
class DbtExecutionContext:
    target: DbtTarget
    env: dict[str, str]
    dbt_vars: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "target": self.target.as_dict(),
            "env": self.env,
            "dbt_vars": self.dbt_vars,
        }


def build_dbt_execution_context(
    project_root: Path,
    schema_dir: Path,
    project_code: str,
    environment: str,
    workload: str,
    *,
    developer: str | None = None,
    pr_number: int | None = None,
    run_id: str | None = None,
    git_sha: str | None = None,
    default_schema: str = "STAGING",
) -> DbtExecutionContext:
    """Resolve physical targets, run query tag and validated dbt vars together."""
    target = resolve_dbt_target(
        project_code,
        environment,
        workload,
        developer=developer,
        pr_number=pr_number,
        default_schema=default_schema,
    )

    project_root = project_root.resolve()
    project = load_document(project_root / "config" / "project.yml")["project"]
    if project["code"] != target.project_code:
        raise ValueError(
            f"project code mismatch: metadata declares {project['code']}, resolver received {target.project_code}"
        )

    query_context: dict[str, object] = {
        "environment": target.environment,
        "workload": target.workload,
        "run_id": run_id,
        "git_sha": git_sha,
        "pr_number": pr_number,
    }
    run_query_tag = build_query_tag(
        {
            "project": target.project_code.lower(),
            "environment": target.environment,
            "workload": target.workload,
            "run_id": run_id,
            "git_sha": git_sha,
            "pr_number": pr_number,
            "operation": "dbt_run",
        }
    )

    env = target.as_env()
    env["DBT_QUERY_TAG"] = run_query_tag

    return DbtExecutionContext(
        target=target,
        env=env,
        dbt_vars=build_dbt_vars(project_root, schema_dir, query_context=query_context),
    )


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """Append single-line non-secret dbt execution metadata to a GitHub-style env file."""
    with path.open("a", encoding="utf-8") as handle:
        for key in sorted(values):
            value = values[key]
            if "\n" in value or "\r" in value:
                raise ValueError(f"environment value for {key} must be single-line")
            handle.write(f"{key}={value}\n")


def write_vars_file(path: Path, values: dict[str, object]) -> None:
    path.write_text(
        json.dumps(values, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
