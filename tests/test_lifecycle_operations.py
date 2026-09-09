from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.cli import _build_parser
from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.lifecycle import generate_lifecycle_scripts
from enterprise_snowflake_framework.scaffold import scaffold_pipeline
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


class DatasetLifecycleOperationTests(unittest.TestCase):
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
        scaffold_pipeline(
            project_root=self.root,
            source_id="fleet_mssql",
            pattern="scd2",
            dataset_id="customer",
        )
        scaffold_version(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            version="v2",
        )

    def test_init_has_lifecycle_and_domain_decommission_guidance(self) -> None:
        self.assertTrue((self.root / "operations" / "lifecycle" / "README.md").is_file())
        runbook = self.root / "docs" / "DOMAIN_DECOMMISSION.md"
        self.assertTrue(runbook.is_file())
        self.assertIn("Physical cleanup is a separate reviewed change", runbook.read_text(encoding="utf-8"))

    def test_pause_and_resume_require_explicit_version(self) -> None:
        with self.assertRaises(ValueError):
            generate_lifecycle_scripts(
                project_root=self.root,
                source_id="fleet_mssql",
                dataset_id="customer",
                action="pause",
                operation_id="pause_without_version",
            )

        paused = generate_lifecycle_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            action="pause",
            operation_id="pause_incident_123",
            version="v1",
        )
        sql = (paused.destination / "operation.sql").read_text(encoding="utf-8")
        self.assertIn("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V1_TASK SUSPEND", sql)
        self.assertIn("SET ENABLED = FALSE", sql)
        self.assertIn("LIFECYCLE_STATUS = 'PAUSED'", sql)
        self.assertIn("050_dataset_lifecycle_status.sql", sql)
        self.assertIn("`esf` does not execute this file", sql)

        resumed = generate_lifecycle_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            action="resume",
            operation_id="resume_incident_123",
            version="v1",
        )
        sql = (resumed.destination / "operation.sql").read_text(encoding="utf-8")
        self.assertIn("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V1_TASK RESUME", sql)
        self.assertIn("SET ENABLED = TRUE", sql)
        self.assertIn("LIFECYCLE_STATUS = 'ACTIVE'", sql)

    def test_soft_decommission_stops_all_versions_but_does_not_drop_data(self) -> None:
        result = generate_lifecycle_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            action="decommission",
            operation_id="decommission_2026q4",
        )
        sql = (result.destination / "operation.sql").read_text(encoding="utf-8")
        self.assertIn("FLEET_MSSQL_CUSTOMER_V1_TASK SUSPEND", sql)
        self.assertIn("FLEET_MSSQL_CUSTOMER_V2_TASK SUSPEND", sql)
        self.assertIn("SET ENABLED = FALSE", sql)
        self.assertIn("LIFECYCLE_STATUS = 'DECOMMISSIONED'", sql)
        self.assertIn("STATUS = 'RETIRED'", sql)
        self.assertIn("does NOT DROP Silver history", sql)
        active_drop_lines = [
            line for line in sql.splitlines() if line.strip().upper().startswith("DROP ")
        ]
        self.assertEqual([], active_drop_lines)

    def test_lifecycle_operation_directory_is_never_overwritten(self) -> None:
        result = generate_lifecycle_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            action="pause",
            operation_id="pause_once",
            version="v1",
        )
        operation = result.destination / "operation.sql"
        operation.write_text("-- DOMAIN REVIEWED LIFECYCLE\n", encoding="utf-8")
        repeated = generate_lifecycle_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            action="pause",
            operation_id="pause_once",
            version="v1",
        )
        self.assertFalse(repeated.created)
        self.assertEqual("-- DOMAIN REVIEWED LIFECYCLE\n", operation.read_text(encoding="utf-8"))

    def test_decommission_rejects_version_argument(self) -> None:
        with self.assertRaises(ValueError):
            generate_lifecycle_scripts(
                project_root=self.root,
                source_id="fleet_mssql",
                dataset_id="customer",
                action="decommission",
                operation_id="bad_decommission",
                version="v1",
            )

    def test_cli_exposes_lifecycle_sql_and_no_force(self) -> None:
        parser = _build_parser()
        parsed = parser.parse_args(
            [
                "lifecycle-sql",
                "customer",
                "pause_incident_123",
                "--source",
                "fleet_mssql",
                "--action",
                "pause",
                "--version",
                "v1",
            ]
        )
        self.assertEqual("lifecycle-sql", parsed.command)
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "lifecycle-sql",
                    "customer",
                    "pause_incident_123",
                    "--source",
                    "fleet_mssql",
                    "--action",
                    "pause",
                    "--version",
                    "v1",
                    "--force",
                ]
            )


if __name__ == "__main__":
    unittest.main()
