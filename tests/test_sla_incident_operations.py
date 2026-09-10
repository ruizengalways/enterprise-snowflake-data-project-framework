from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.cli import _build_parser
from enterprise_snowflake_framework.control_plan import build_control_plan
from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.scaffold import scaffold_pipeline
from enterprise_snowflake_framework.sla_policy import generate_sla_sql
from enterprise_snowflake_framework.source_management import add_source
from enterprise_snowflake_framework.versioning import scaffold_version


RAW = """schema_version: 2
contract:
  source_system: fleet_mssql
  entity: customer
  grain: one row per source change
  business_key: [id]
  source_timestamp: source_updated_at
  columns:
    - {name: id, type: VARCHAR, nullable: false}
    - {name: status, type: VARCHAR, nullable: true}
    - {name: source_updated_at, type: TIMESTAMP_NTZ, nullable: false}
    - {name: source_sequence, type: NUMBER, nullable: false}
    - {name: source_operation, type: VARCHAR, nullable: false}
    - {name: ingested_at, type: TIMESTAMP_LTZ, nullable: false}
  change_semantics:
    mode: cdc
    operation_column: source_operation
    sequence_column: source_sequence
    delete_semantics: tombstone
    delete_values: [D]
  capture_fidelity: full_change
  ordering_columns: [source_updated_at, source_sequence]
  idempotency_key: [id, source_sequence]
  breaking_change_policy: versioned_contract
"""


class SlaIncidentOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(self.root)
        add_source(self.root, "fleet_mssql")
        raw = self.root / "contracts" / "raw" / "fleet_mssql" / "customer.yml"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(RAW, encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "source": {"id": "fleet_mssql", "owner": "transport"},
            "datasets": {
                "customer": {
                    "pattern": "scd2",
                    "raw_contract": "contracts/raw/fleet_mssql/customer.yml",
                }
            },
        }
        (self.root / "config" / "sources" / "fleet_mssql.yml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )

    def test_fresh_init_has_complete_domain_control_plane(self) -> None:
        expected = {
            "001_objects.sql",
            "010_observability_views.sql",
            "020_refresh_health.sql",
            "030_sla_incident_lifecycle.sql",
            "040_health_task.sql",
            "050_dataset_lifecycle_status.sql",
            "060_run_evidence_api.sql",
        }
        actual = {path.name for path in (self.root / "control_plane" / "sql").glob("*.sql")}
        self.assertEqual(expected, actual)
        plan = build_control_plan(self.root)
        self.assertTrue(plan.ready)
        self.assertEqual((), plan.known_files_missing)
        self.assertEqual((), plan.missing_from_manifest)

    def test_old_domain_upgrade_is_non_destructive_and_control_plan_exposes_manifest_gap(self) -> None:
        manifest = self.root / "control_plane" / "deploy_manifest.txt"
        old_manifest = (
            "control_plane/sql/001_objects.sql\n"
            "control_plane/sql/010_observability_views.sql\n"
            "control_plane/sql/020_refresh_health.sql\n"
        )
        manifest.write_text(old_manifest, encoding="utf-8")
        for name in (
            "030_sla_incident_lifecycle.sql",
            "040_health_task.sql",
            "050_dataset_lifecycle_status.sql",
            "060_run_evidence_api.sql",
        ):
            (self.root / "control_plane" / "sql" / name).unlink()

        initialize_project(self.root)

        self.assertEqual(old_manifest, manifest.read_text(encoding="utf-8"))
        plan = build_control_plan(self.root)
        self.assertEqual((), plan.known_files_missing)
        self.assertEqual(
            (
                "control_plane/sql/030_sla_incident_lifecycle.sql",
                "control_plane/sql/040_health_task.sql",
                "control_plane/sql/050_dataset_lifecycle_status.sql",
                "control_plane/sql/060_run_evidence_api.sql",
            ),
            plan.missing_from_manifest,
        )
        self.assertFalse(plan.ready)

    def test_lifecycle_status_migration_makes_dashboard_state_explicit(self) -> None:
        sql = (
            self.root / "control_plane" / "sql" / "050_dataset_lifecycle_status.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS LIFECYCLE_STATUS", sql)
        self.assertIn("THEN 'DECOMMISSIONED'", sql)
        self.assertIn("H.HEALTH_REASON", sql)
        self.assertIn("INCIDENT_KEY", sql)
        self.assertIn("STAGE", sql)

    def test_sla_sql_is_reviewable_and_never_overwrites_revision(self) -> None:
        result = generate_sla_sql(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            policy_id="freshness_v1",
            stage="END_TO_END",
            cadence_type="CONTINUOUS",
            max_freshness_seconds=600,
        )
        self.assertTrue(result.created)
        sql = result.destination.read_text(encoding="utf-8")
        self.assertIn("MERGE INTO CONTROL.SLA_POLICY", sql)
        self.assertIn("'END_TO_END' AS STAGE", sql)
        self.assertIn("600 AS MAX_FRESHNESS_SECONDS", sql)
        self.assertIn("`esf` does not execute this file", sql)

        result.destination.write_text("-- DOMAIN REVIEWED POLICY\n", encoding="utf-8")
        repeated = generate_sla_sql(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            policy_id="freshness_v1",
            stage="END_TO_END",
            cadence_type="CONTINUOUS",
            max_freshness_seconds=900,
        )
        self.assertFalse(repeated.created)
        self.assertEqual("-- DOMAIN REVIEWED POLICY\n", result.destination.read_text(encoding="utf-8"))

    def test_interval_and_scheduled_deadline_policy_validation(self) -> None:
        with self.assertRaises(ValueError):
            generate_sla_sql(
                project_root=self.root,
                source_id="fleet_mssql",
                dataset_id="customer",
                policy_id="bad_interval",
                stage="END_TO_END",
                cadence_type="INTERVAL",
            )

        result = generate_sla_sql(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            policy_id="daily_0400_v1",
            stage="END_TO_END",
            cadence_type="SCHEDULED_DEADLINE",
            deadline_local_time="04:00:00",
            timezone="Australia/Sydney",
        )
        sql = result.destination.read_text(encoding="utf-8")
        self.assertIn("TO_TIME('04:00:00')", sql)
        self.assertIn("'Australia/Sydney' AS TIMEZONE", sql)

    def test_dataset_policy_is_logical_and_candidate_does_not_duplicate_it(self) -> None:
        v1 = scaffold_pipeline(
            project_root=self.root,
            source_id="fleet_mssql",
            pattern="scd2",
            dataset_id="customer",
        ).destination
        self.assertIn(
            "No threshold is guessed by the framework",
            (v1 / "060_policy.sql").read_text(encoding="utf-8"),
        )
        v2 = scaffold_version(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            version="v2",
        ).destination
        self.assertIn(
            "SLA belongs to the logical dataset",
            (v2 / "060_policy.sql").read_text(encoding="utf-8"),
        )

    def test_control_sql_has_cadence_incident_lifecycle_and_serverless_health_task(self) -> None:
        lifecycle = (
            self.root / "control_plane" / "sql" / "030_sla_incident_lifecycle.sql"
        ).read_text(encoding="utf-8")
        task = (self.root / "control_plane" / "sql" / "040_health_task.sql").read_text(encoding="utf-8")
        self.assertIn("CONTROL.SLA_EVALUATION_V", lifecycle)
        self.assertIn("SCHEDULED_DEADLINE", lifecycle)
        self.assertIn("CONTROL.EVALUATE_DOMAIN_HEALTH", lifecycle)
        self.assertIn("INCIDENT_KEY", lifecycle)
        self.assertIn("STATUS = 'RESOLVED'", lifecycle)
        self.assertIn("USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE", task)
        self.assertIn("SCHEDULE = '1 MINUTE'", task)
        self.assertNotIn("WAREHOUSE = WH_", task)

    def test_cli_exposes_control_plan_and_sla_sql_without_force(self) -> None:
        parser = _build_parser()
        control = parser.parse_args(["control-plan", "--project-root", str(self.root)])
        self.assertEqual("control-plan", control.command)
        policy = parser.parse_args(
            [
                "sla-sql",
                "customer",
                "freshness_v1",
                "--source",
                "fleet_mssql",
                "--stage",
                "END_TO_END",
                "--cadence",
                "CONTINUOUS",
                "--max-freshness-seconds",
                "600",
            ]
        )
        self.assertEqual("sla-sql", policy.command)
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "sla-sql",
                    "customer",
                    "freshness_v1",
                    "--source",
                    "fleet_mssql",
                    "--stage",
                    "END_TO_END",
                    "--cadence",
                    "CONTINUOUS",
                    "--max-freshness-seconds",
                    "600",
                    "--force",
                ]
            )


if __name__ == "__main__":
    unittest.main()
