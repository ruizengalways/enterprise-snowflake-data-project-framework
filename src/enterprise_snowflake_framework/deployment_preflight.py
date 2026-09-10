from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from .control_plan import KNOWN_CONTROL_SQL, ControlPlan, build_control_plan


@dataclass(frozen=True)
class DeploymentPreflight:
    project_root: Path
    control_plan: ControlPlan
    errors: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.errors


def build_deployment_preflight(project_root: Path) -> DeploymentPreflight:
    project_root = project_root.resolve()
    plan = build_control_plan(project_root)
    errors: list[str] = []

    if not plan.manifest.is_file():
        errors.append(f"control-plane deploy manifest not found: {plan.manifest}")

    for path in plan.known_files_missing:
        errors.append(f"known control migration missing from repository: {path}")

    for path in plan.missing_from_manifest:
        errors.append(f"known control migration missing from deploy manifest: {path}")

    for path in plan.duplicate_manifest_entries:
        errors.append(f"duplicate control deploy-manifest entry: {path}")

    if not plan.known_order_valid:
        expected = " -> ".join(KNOWN_CONTROL_SQL)
        actual = " -> ".join(plan.known_manifest_entries)
        errors.append(
            "known control migrations are out of order; "
            f"expected framework order: {expected}; actual known order: {actual}"
        )

    return DeploymentPreflight(
        project_root=project_root,
        control_plan=plan,
        errors=tuple(errors),
    )


def render_deployment_preflight(result: DeploymentPreflight) -> str:
    lines = [
        f"Project root: {result.project_root}",
        f"Control manifest: {result.control_plan.manifest}",
        f"Deployment preflight: {'READY' if result.ready else 'BLOCKED'}",
        "",
    ]
    if result.errors:
        lines.append("BLOCKING CONTROL-PLANE GAPS")
        lines.extend(f"  - {error}" for error in result.errors)
    else:
        lines.append("Current framework control-plane baseline is present exactly once and in order.")

    if result.control_plan.unknown_manifest_entries:
        lines.extend(
            [
                "",
                "DOMAIN-OWNED CONTROL ENTRIES (allowed)",
                *[f"  - {path}" for path in result.control_plan.unknown_manifest_entries],
            ]
        )

    lines.extend(["", "No files changed."])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="esf-control-preflight",
        description=(
            "Fail closed before Snowflake authentication when the domain control-plane baseline "
            "is incomplete, duplicated, or out of framework migration order."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    result = build_deployment_preflight(args.project_root)
    print(render_deployment_preflight(result), end="")
    if not result.ready:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
