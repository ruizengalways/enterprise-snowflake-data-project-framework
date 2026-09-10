from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.control_plan import KNOWN_CONTROL_SQL, build_control_plan
from enterprise_snowflake_framework.deployment_preflight import (
    build_deployment_preflight,
    render_deployment_preflight,
)
from enterprise_snowflake_framework.init_project import initialize_project


class DeploymentPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(self.root)
        self.manifest = self.root / "control_plane" / "deploy_manifest.txt"

    def test_fresh_project_is_ready(self) -> None:
        result = build_deployment_preflight(self.root)
        self.assertTrue(result.ready)
        self.assertTrue(result.control_plan.ready)
        self.assertEqual((), result.errors)
        text = render_deployment_preflight(result)
        self.assertIn("Deployment preflight: READY", text)
        self.assertIn("No files changed.", text)

    def test_installed_entrypoint_returns_zero_for_ready_project(self) -> None:
        completed = subprocess.run(
            ["esf-control-preflight", "--project-root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("Deployment preflight: READY", completed.stdout)

    def test_missing_known_migration_blocks_before_deployment(self) -> None:
        missing = KNOWN_CONTROL_SQL[-1]
        text = self.manifest.read_text(encoding="utf-8").replace(f"{missing}\n", "")
        self.manifest.write_text(text, encoding="utf-8")

        result = build_deployment_preflight(self.root)

        self.assertFalse(result.ready)
        self.assertIn(
            f"known control migration missing from deploy manifest: {missing}",
            result.errors,
        )
        self.assertIn("Deployment preflight: BLOCKED", render_deployment_preflight(result))

        completed = subprocess.run(
            ["esf-control-preflight", "--project-root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn(missing, completed.stdout)

    def test_known_migrations_out_of_order_block(self) -> None:
        entries = [
            line
            for line in self.manifest.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        entries[-2], entries[-1] = entries[-1], entries[-2]
        self.manifest.write_text("\n".join(entries) + "\n", encoding="utf-8")

        plan = build_control_plan(self.root)
        result = build_deployment_preflight(self.root)

        self.assertFalse(plan.known_order_valid)
        self.assertFalse(result.ready)
        self.assertTrue(any("known control migrations are out of order" in item for item in result.errors))

    def test_duplicate_manifest_entry_blocks(self) -> None:
        duplicate = KNOWN_CONTROL_SQL[-1]
        with self.manifest.open("a", encoding="utf-8") as handle:
            handle.write(f"{duplicate}\n")

        plan = build_control_plan(self.root)
        result = build_deployment_preflight(self.root)

        self.assertEqual((duplicate,), plan.duplicate_manifest_entries)
        self.assertFalse(result.ready)
        self.assertIn(f"duplicate control deploy-manifest entry: {duplicate}", result.errors)

    def test_domain_owned_control_entries_are_allowed_without_reordering_framework_migrations(self) -> None:
        custom = "control_plane/sql/900_domain_specific_policy.sql"
        custom_path = self.root / custom
        custom_path.write_text("-- domain-owned migration\n", encoding="utf-8")
        with self.manifest.open("a", encoding="utf-8") as handle:
            handle.write(f"{custom}\n")

        result = build_deployment_preflight(self.root)

        self.assertTrue(result.ready)
        self.assertEqual((custom,), result.control_plan.unknown_manifest_entries)
        rendered = render_deployment_preflight(result)
        self.assertIn("DOMAIN-OWNED CONTROL ENTRIES (allowed)", rendered)
        self.assertIn(custom, rendered)

    def test_missing_manifest_blocks_instead_of_silently_skipping_control_plane(self) -> None:
        self.manifest.unlink()

        result = build_deployment_preflight(self.root)

        self.assertFalse(result.ready)
        self.assertTrue(any("deploy manifest not found" in item for item in result.errors))


if __name__ == "__main__":
    unittest.main()
