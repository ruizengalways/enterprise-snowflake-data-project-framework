from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.cli import _build_parser
from enterprise_snowflake_framework.control_plan import KNOWN_CONTROL_SQL, build_control_plan
from enterprise_snowflake_framework.health_cadence import generate_health_cadence_scripts
from enterprise_snowflake_framework.init_project import initialize_project


class HealthEvaluationCadenceTests(unittest.TestCase):
    def _project(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(root)
        return tmp, root

    def _snapshot(self, root: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_fresh_project_contains_new_migration_without_changing_released_040(self) -> None:
        _, root = self._project()
        migration130 = root / "control_plane" / "sql" / "130_health_evaluation_cadence.sql"
        migration040 = root / "control_plane" / "sql" / "040_health_task.sql"
        manifest = (root / "control_plane" / "deploy_manifest.txt").read_text(encoding="utf-8")

        self.assertTrue(migration130.is_file())
        self.assertIn("control_plane/sql/130_health_evaluation_cadence.sql", manifest)
        self.assertIn("SCHEDULE = '1 MINUTE'", migration040.read_text(encoding="utf-8"))
        sql130 = migration130.read_text(encoding="utf-8")
        self.assertIn("CONTROL.HEALTH_EVALUATION_CHANGE", sql130)
        self.assertIn("CONTROL.HEALTH_EVALUATION_CONFIG_V", sql130)
        self.assertNotIn("ALTER TASK", "\n".join(
            line for line in sql130.splitlines() if not line.lstrip().startswith("--")
        ))
        self.assertEqual(
            "control_plane/sql/130_health_evaluation_cadence.sql", KNOWN_CONTROL_SQL[-1]
        )
        self.assertTrue(build_control_plan(root).ready)

    def test_operation_is_explicit_audited_and_generated_once(self) -> None:
        _, root = self._project()
        result = generate_health_cadence_scripts(
            project_root=root,
            operation_id="health-every-5m",
            interval_seconds=300,
            reason="Five-minute domain health cadence",
            resume_after=True,
        )
        self.assertTrue(result.created)
        operation = (result.destination / "operation.sql").read_text(encoding="utf-8")
        self.assertLess(operation.index("'STARTED'"), operation.index("ALTER TASK CONTROL.EVALUATE_DOMAIN_HEALTH_TASK SUSPEND"))
        self.assertLess(operation.index(" SUSPEND;"), operation.index("SET SCHEDULE = '300 SECONDS'"))
        self.assertLess(operation.index("SET SCHEDULE = '300 SECONDS'"), operation.index(" RESUME;"))
        self.assertLess(operation.index(" RESUME;"), operation.index("SET STATUS = 'SUCCEEDED'"))
        self.assertIn("CURRENT_USER()", operation)
        self.assertIn("Health cadence operation id already exists", operation)
        self.assertNotIn("CREATE OR REPLACE TASK", operation)

        before = self._snapshot(root)
        again = generate_health_cadence_scripts(
            project_root=root,
            operation_id="health-every-5m",
            interval_seconds=600,
            reason="different arguments must not rewrite an owned operation",
            resume_after=False,
        )
        self.assertFalse(again.created)
        self.assertEqual(before, self._snapshot(root))

    def test_leave_suspended_is_an_explicit_final_state(self) -> None:
        _, root = self._project()
        result = generate_health_cadence_scripts(
            project_root=root,
            operation_id="maintenance-cadence",
            interval_seconds=900,
            reason="Prepare health task during maintenance",
            resume_after=False,
        )
        operation = (result.destination / "operation.sql").read_text(encoding="utf-8")
        self.assertIn("'SUSPENDED'", operation)
        self.assertIn("leave the health evaluation Task suspended", operation)
        self.assertNotIn("CONTROL.EVALUATE_DOMAIN_HEALTH_TASK RESUME;", operation)

    def test_interval_range_and_reason_fail_closed_before_writes(self) -> None:
        _, root = self._project()
        before = self._snapshot(root)
        for value in (9, 691201):
            with self.assertRaisesRegex(ValueError, "between 10 and 691200"):
                generate_health_cadence_scripts(
                    project_root=root,
                    operation_id=f"bad-{value}",
                    interval_seconds=value,
                    reason="invalid bound",
                    resume_after=False,
                )
        with self.assertRaisesRegex(ValueError, "reason is required"):
            generate_health_cadence_scripts(
                project_root=root,
                operation_id="missing-reason",
                interval_seconds=60,
                reason="   ",
                resume_after=False,
            )
        self.assertEqual(before, self._snapshot(root))

    def test_reason_is_sql_escaped_and_operation_is_not_sla_metadata(self) -> None:
        _, root = self._project()
        result = generate_health_cadence_scripts(
            project_root=root,
            operation_id="quoted-reason",
            interval_seconds=120,
            reason="Owner's reviewed cadence",
            resume_after=True,
        )
        operation = (result.destination / "operation.sql").read_text(encoding="utf-8")
        self.assertIn("'Owner''s reviewed cadence'", operation)
        self.assertNotIn("CONTROL.SLA_POLICY", operation)
        project = (root / "config" / "project.yml").read_text(encoding="utf-8")
        self.assertNotIn("health", project.lower())

    def test_cli_requires_explicit_final_state_choice(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([
            "health-cadence-sql", "health-every-5m",
            "--interval-seconds", "300",
            "--reason", "reviewed",
            "--resume-after",
        ])
        self.assertEqual("health-cadence-sql", args.command)
        self.assertTrue(args.resume_after)
        self.assertFalse(args.leave_suspended)

        with self.assertRaises(SystemExit):
            parser.parse_args([
                "health-cadence-sql", "missing-state",
                "--interval-seconds", "300",
                "--reason", "reviewed",
            ])

    def test_old_domain_rerun_materializes_130_without_rewriting_manifest(self) -> None:
        _, root = self._project()
        manifest_path = root / "control_plane" / "deploy_manifest.txt"
        old_manifest = manifest_path.read_text(encoding="utf-8").replace(
            "control_plane/sql/130_health_evaluation_cadence.sql\n", ""
        )
        manifest_path.write_text(old_manifest, encoding="utf-8")
        (root / "control_plane" / "sql" / "130_health_evaluation_cadence.sql").unlink()

        initialize_project(root)

        self.assertTrue((root / "control_plane" / "sql" / "130_health_evaluation_cadence.sql").is_file())
        self.assertEqual(old_manifest, manifest_path.read_text(encoding="utf-8"))
        plan = build_control_plan(root)
        self.assertIn("control_plane/sql/130_health_evaluation_cadence.sql", plan.missing_from_manifest)
        self.assertFalse(plan.ready)


if __name__ == "__main__":
    unittest.main()
