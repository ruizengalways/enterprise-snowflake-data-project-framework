from __future__ import annotations

import argparse
import re
import subprocess

_CONTROL_TEMPLATE_RE = re.compile(
    r"^src/enterprise_snowflake_framework/templates/project/control_plane_[0-9]{3}_.+\.sql$"
)


def changed_released_control_migrations(diff_text: str) -> tuple[str, ...]:
    violations: list[str] = []
    for raw in diff_text.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        status = parts[0]
        paths = parts[1:]
        for path in paths:
            if _CONTROL_TEMPLATE_RE.fullmatch(path) and not status.startswith("A"):
                violations.append(f"{status}\t{path}")
    return tuple(violations)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Block modification, deletion or rename of already-released numbered control migration "
            "templates. New numbered migrations may be added."
        )
    )
    parser.add_argument("--base", required=True, help="Base Git commit SHA for the pull request.")
    args = parser.parse_args()

    completed = subprocess.run(
        ["git", "diff", "--name-status", "--find-renames", f"{args.base}...HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    violations = changed_released_control_migrations(completed.stdout)
    if violations:
        print("Released control migration templates are immutable. Add a later migration instead:")
        for item in violations:
            print(f"  {item}")
        raise SystemExit(2)

    print("Released control migration templates unchanged; newly added numbered migrations are allowed.")


if __name__ == "__main__":
    main()
