from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.cli import _build_parser
from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.repair import build_repair_plan, generate_silver_repair_scripts
from enterprise_snowflake_framework.scaffold import scaffold_pipeline, scaffold_preview
from enterprise_snowflake_framework.source_management import add_source
from enterprise_snowflake_framework.versioning import generate_release_scripts, scaffold_version


RAW_TEMPLATE = """schema_version: 2
contract:
  source_system: {source}
  entity: customer
  grain: one row per source change
  business_key:
    - id
  source_timestamp: source_updated_at
  columns:
    - name: id
      type: VARCHAR
      nullable: false
    - name: name
      type: VARCHAR
      nullable: true
    - name: status
      type: VARCHAR
      nullable: true
    - name: source_updated_at
      type: TIMESTAMP_NTZ
      nullable: false
    - name: source_sequence
      type: NUMBER
      nullable: false
    - name: source_operation
      type: VARCHAR
      nullable: false
    - name: ingested_at
      type: TIMESTAMP_LTZ
      nullable: false
  change_semantics:
    mode: cdc
    operation_column: source_operation
    sequence_column: source_sequence
    delete_semantics: tombstone
    delete_values: [D]
  capture_fidelity: full_change
  ordering_columns:
    - source_updated_at
    - source_sequence
  idempotency_key:
    - id
    - source_sequence
  breaking_change_policy: versioned_contract
"""


class VersionedPipelineOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(self.root)
        self._source("fleet_mssql")

    def _source(self, source: str) -> None:
        add_source(self.root, source)
        raw_root = self.root / "contracts" / "raw" / source
        raw_root.mkdir(parents=True, exist_ok=True)
        (raw_root / "customer.yml").write_text(RAW_TEMPLATE.format(source=source), encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "source": {"id": source, "owner": "transport"},
            "datasets": {
                "customer": {
                    "pattern": "scd2",
                    "raw_contract": f"contracts/raw/{source}/customer.yml",
                }
            },
        }
        (self.root / "config" / "sources" / f"{source}.yml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )

    def _scaffold_v1(self, source: str = "fleet_mssql") -> Path:
        return scaffold_pipeline(
            project_root=self.root,
            source_id=source,
            pattern="scd2",
            dataset_id="customer",
        ).destination

    def test_preview_is_read_only_and_source_scoped(self) -> None:
        destination = self.root / "silver_processing" / "fleet_mssql" / "customer"
        result = scaffold_preview(
            project_root=self.root, source_id="fleet_mssql", dataset_id="customer"
        )
        self.assertFalse(result.domain_owned)
        self.assertFalse(destination.exists())
        self.assertIn("010_apply.sql", result.files)
        self.assertIn("025_compare.sql", result.files)
        self.assertIn("060_policy.sql", result.files)
        self.assertIn("BRONZE.FLEET_MSSQL_CUSTOMER", result.rendered["pipeline.yml"])
        self.assertIn("SILVER.FLEET_MSSQL_CUSTOMER_HISTORY", result.rendered["pipeline.yml"])

    def test_v1_scaffold_generates_explicit_operational_pipeline(self) -> None:
        destination = self._scaffold_v1()
        expected = {
            "README.md",
            "pipeline.yml",
            "version.yml",
            "001_objects.sql",
            "010_apply.sql",
            "015_replay.sql",
            "020_validate.sql",
            "025_compare.sql",
            "030_task.sql",
            "040_register.sql",
            "050_publish.sql",
            "060_policy.sql",
            "deploy_manifest.fragment.txt",
        }
        self.assertEqual(expected, {path.name for path in destination.iterdir() if path.is_file()})
        objects = (destination / "001_objects.sql").read_text(encoding="utf-8")
        apply_sql = (destination / "010_apply.sql").read_text(encoding="utf-8")
        task_sql = (destination / "030_task.sql").read_text(encoding="utf-8")
        publish = (destination / "050_publish.sql").read_text(encoding="utf-8")
        register = (destination / "040_register.sql").read_text(encoding="utf-8")
        compare = (destination / "025_compare.sql").read_text(encoding="utf-8")
        policy = (destination / "060_policy.sql").read_text(encoding="utf-8")
        self.assertIn("FLEET_MSSQL_CUSTOMER_V1_HISTORY", objects)
        self.assertIn("FLEET_MSSQL_CUSTOMER_V1_CURRENT", objects)
        self.assertIn("IS_ACTIVE = TRUE", objects)
        self.assertIn("CREATE OR REPLACE PROCEDURE SILVER.APPLY_FLEET_MSSQL_CUSTOMER_V1", apply_sql)
        self.assertIn("SYSTEM$STREAM_HAS_DATA", task_sql)
        self.assertIn("WH_TRANSPORT_TRANSFORM", task_sql)
        self.assertIn("SILVER.FLEET_MSSQL_CUSTOMER_CURRENT", publish)
        self.assertIn("CONTROL.DATASET_VERSION", register)
        self.assertIn("initial implementation has no prior active version", compare)
        self.assertIn("No threshold is guessed by the framework", policy)
        self.assertIn("esf sla-sql", policy)

    def test_candidate_is_independent_and_never_rewrites_v1(self) -> None:
        destination = self._scaffold_v1()
        v1_apply = destination / "010_apply.sql"
        custom = "-- DOMAIN V1 CUSTOM LOGIC\n"
        v1_apply.write_text(custom, encoding="utf-8")
        result = scaffold_version(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            version="v2",
        )
        self.assertTrue(result.created)
        self.assertEqual(custom, v1_apply.read_text(encoding="utf-8"))
        self.assertIn(
            "FLEET_MSSQL_CUSTOMER_V2_HISTORY",
            (result.destination / "001_objects.sql").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "Candidate v2 is intentionally not published",
            (result.destination / "050_publish.sql").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "SLA belongs to the logical dataset",
            (result.destination / "060_policy.sql").read_text(encoding="utf-8"),
        )
        compare = (result.destination / "025_compare.sql").read_text(encoding="utf-8")
        self.assertIn("CONTROL.VERSION_VALIDATION", compare)
        self.assertIn("SILVER.FLEET_MSSQL_CUSTOMER_CURRENT", compare)
        self.assertIn("SILVER.FLEET_MSSQL_CUSTOMER_V2_CURRENT", compare)
        marker = result.destination / "010_apply.sql"
        marker.write_text("-- DOMAIN V2 CUSTOM\n", encoding="utf-8")
        repeated = scaffold_version(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            version="v2",
        )
        self.assertFalse(repeated.created)
        self.assertEqual("-- DOMAIN V2 CUSTOM\n", marker.read_text(encoding="utf-8"))

    def test_release_sql_is_explicit_and_not_executed(self) -> None:
        self._scaffold_v1()
        scaffold_version(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            version="v2",
        )
        result = generate_release_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            from_version="v1",
            to_version="v2",
        )
        activate = (result.destination / "activate.sql").read_text(encoding="utf-8")
        rollback = (result.destination / "rollback.sql").read_text(encoding="utf-8")
        self.assertIn("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V1_TASK SUSPEND", activate)
        self.assertIn("FROM SILVER.FLEET_MSSQL_CUSTOMER_V2_HISTORY", activate)
        self.assertIn("ACTIVE_VERSION = 'v2'", activate)
        self.assertIn("FROM SILVER.FLEET_MSSQL_CUSTOMER_V1_HISTORY", rollback)
        marker = result.destination / "activate.sql"
        marker.write_text("-- REVIEWED CUSTOM RELEASE\n", encoding="utf-8")
        repeated = generate_release_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            from_version="v1",
            to_version="v2",
        )
        self.assertFalse(repeated.created)
        self.assertEqual("-- REVIEWED CUSTOM RELEASE\n", marker.read_text(encoding="utf-8"))

    def test_repair_plan_and_repair_sql_preserve_active(self) -> None:
        self._scaffold_v1()
        scaffold_version(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            version="v2",
        )
        plan = build_repair_plan(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            problem="silver",
            requested_from="2026-09-01 00:00:00",
        )
        self.assertEqual("v3", plan.recommended_candidate)
        self.assertFalse(plan.active_production_overwrite)
        scripts = generate_silver_repair_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            candidate_version="v2",
            requested_from="2026-09-01 00:00:00",
        )
        repair = (scripts.destination / "repair.sql").read_text(encoding="utf-8")
        self.assertIn("REPLAY_FLEET_MSSQL_CUSTOMER_V2", repair)
        self.assertIn("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V2_TASK SUSPEND", repair)
        self.assertNotIn("FLEET_MSSQL_CUSTOMER_V1_HISTORY", repair)
        self.assertNotIn("ACTIVE_VERSION", repair)

    def test_same_dataset_name_in_two_sources_does_not_collide(self) -> None:
        self._source("crm_postgres")
        fleet = self._scaffold_v1("fleet_mssql")
        crm = self._scaffold_v1("crm_postgres")
        fleet_objects = (fleet / "001_objects.sql").read_text(encoding="utf-8")
        crm_objects = (crm / "001_objects.sql").read_text(encoding="utf-8")
        self.assertIn("FLEET_MSSQL_CUSTOMER_V1_HISTORY", fleet_objects)
        self.assertIn("CRM_POSTGRES_CUSTOMER_V1_HISTORY", crm_objects)
        self.assertNotEqual(fleet_objects, crm_objects)

    def test_cli_has_safe_operational_commands_and_no_force(self) -> None:
        parser = _build_parser()
        parsed = parser.parse_args(
            ["repair-plan", "customer", "--source", "fleet_mssql", "--problem", "silver"]
        )
        self.assertEqual("repair-plan", parsed.command)
        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["scaffold-version", "customer", "v2", "--source", "fleet_mssql", "--force"]
            )


if __name__ == "__main__":
    unittest.main()
