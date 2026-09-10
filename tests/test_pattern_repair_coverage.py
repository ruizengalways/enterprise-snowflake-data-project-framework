from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.repair import build_repair_plan, generate_silver_repair_scripts
from enterprise_snowflake_framework.scaffold import scaffold_pipeline
from enterprise_snowflake_framework.source_management import add_source
from enterprise_snowflake_framework.versioning import scaffold_version


RAW_TEMPLATE = """schema_version: 2
contract:
  source_system: fleet_mssql
  entity: {dataset}
  grain: one row per source change
  business_key: [id]
  source_timestamp: source_updated_at
  columns:
    - {{name: id, type: VARCHAR, nullable: false}}
    - {{name: value, type: VARCHAR, nullable: true}}
    - {{name: source_updated_at, type: TIMESTAMP_NTZ, nullable: false}}
    - {{name: source_sequence, type: NUMBER, nullable: false}}
    - {{name: source_operation, type: VARCHAR, nullable: false}}
    - {{name: ingested_at, type: TIMESTAMP_LTZ, nullable: false}}
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


class PatternRepairCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(self.root)
        add_source(self.root, "fleet_mssql")
        self.manifest_path = self.root / "config" / "sources" / "fleet_mssql.yml"
        self.manifest = {
            "schema_version": 1,
            "source": {"id": "fleet_mssql", "owner": "transport"},
            "datasets": {},
        }

    def _dataset(self, dataset: str, pattern: str) -> Path:
        raw = self.root / "contracts" / "raw" / "fleet_mssql" / f"{dataset}.yml"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(RAW_TEMPLATE.format(dataset=dataset), encoding="utf-8")
        self.manifest["datasets"][dataset] = {
            "pattern": pattern,
            "raw_contract": f"contracts/raw/fleet_mssql/{dataset}.yml",
        }
        self.manifest_path.write_text(yaml.safe_dump(self.manifest, sort_keys=False), encoding="utf-8")
        v1 = scaffold_pipeline(
            project_root=self.root,
            source_id="fleet_mssql",
            pattern=pattern,
            dataset_id=dataset,
        ).destination
        scaffold_version(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id=dataset,
            version="v2",
        )
        return v1

    def test_append_has_deterministic_candidate_replay_and_repair_script(self) -> None:
        v1 = self._dataset("events", "append")
        replay = (v1 / "015_replay.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE PROCEDURE SILVER.REPLAY_FLEET_MSSQL_EVENTS_V1", replay)
        self.assertNotIn("CREATE OR REPLACE PROCEDURE SILVER.REPLAY_", replay)
        self.assertIn("DELETE FROM SILVER.FLEET_MSSQL_EVENTS_V1", replay)
        self.assertIn("NOT EXISTS", replay)
        self.assertIn("CONTROL.REPAIR_RUN", replay)
        self.assertIn("deterministic full candidate rebuild", replay)

        repair = generate_silver_repair_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="events",
            candidate_version="v2",
            requested_from="2026-09-01 00:00:00",
        )
        sql = (repair.destination / "repair.sql").read_text(encoding="utf-8")
        self.assertIn("pattern append", sql)
        self.assertIn("REPLAY_FLEET_MSSQL_EVENTS_V2", sql)
        self.assertIn("TO_TIMESTAMP_NTZ('2026-09-01 00:00:00')", sql)
        self.assertNotIn("FLEET_MSSQL_EVENTS_V1", sql)

    def test_scd1_replay_recomputes_current_state_from_ordered_bronze(self) -> None:
        v1 = self._dataset("customer", "scd1")
        replay = (v1 / "015_replay.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE PROCEDURE SILVER.REPLAY_FLEET_MSSQL_CUSTOMER_V1", replay)
        self.assertNotIn("CREATE OR REPLACE PROCEDURE SILVER.REPLAY_", replay)
        self.assertIn("DELETE FROM SILVER.FLEET_MSSQL_CUSTOMER_V1", replay)
        self.assertIn("MERGE INTO SILVER.FLEET_MSSQL_CUSTOMER_V1", replay)
        self.assertIn("ROW_NUMBER() OVER", replay)
        self.assertIn("SOURCE_UPDATED_AT DESC", replay)
        self.assertIn("SOURCE_OPERATION", replay)
        self.assertIn("THEN DELETE", replay)
        self.assertIn("CONTROL.REPAIR_RUN", replay)

        result = generate_silver_repair_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            candidate_version="v2",
        )
        sql = (result.destination / "repair.sql").read_text(encoding="utf-8")
        self.assertIn("pattern scd1", sql)
        self.assertIn("NULL,\n    NULL", sql)
        self.assertIn("full candidate bootstrap", sql)

    def test_full_refresh_repair_is_snapshot_rebuild_and_rejects_ranges(self) -> None:
        v1 = self._dataset("reference_codes", "full_refresh")
        replay = (v1 / "015_replay.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE PROCEDURE SILVER.REPLAY_FLEET_MSSQL_REFERENCE_CODES_V1()", replay)
        self.assertNotIn("CREATE OR REPLACE PROCEDURE SILVER.REPLAY_", replay)
        self.assertIn("INSERT OVERWRITE INTO SILVER.FLEET_MSSQL_REFERENCE_CODES_V1", replay)
        self.assertIn("current Bronze snapshot", replay)
        self.assertNotIn("P_FROM TIMESTAMP_NTZ", replay)

        with self.assertRaises(ValueError):
            generate_silver_repair_scripts(
                project_root=self.root,
                source_id="fleet_mssql",
                dataset_id="reference_codes",
                candidate_version="v2",
                requested_from="2026-09-01 00:00:00",
            )

        result = generate_silver_repair_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="reference_codes",
            candidate_version="v2",
        )
        sql = (result.destination / "repair.sql").read_text(encoding="utf-8")
        self.assertIn("CALL SILVER.REPLAY_FLEET_MSSQL_REFERENCE_CODES_V2();", sql)
        self.assertIn("no time range is applied", sql)

    def test_scd2_replay_keeps_affected_key_history_rebuild(self) -> None:
        v1 = self._dataset("account", "scd2")
        replay = (v1 / "015_replay.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE PROCEDURE SILVER.REPLAY_FLEET_MSSQL_ACCOUNT_V1", replay)
        self.assertNotIn("CREATE OR REPLACE PROCEDURE SILVER.REPLAY_", replay)
        self.assertIn("ESF_AFFECTED_KEYS", replay)
        self.assertIn("DELETE FROM SILVER.FLEET_MSSQL_ACCOUNT_V1_EVENTS", replay)
        self.assertIn("SILVER.FLEET_MSSQL_ACCOUNT_V1_HISTORY", replay)
        self.assertIn("LAG(", replay)
        self.assertIn("LEAD(", replay)
        self.assertIn("CONTROL.REPAIR_RUN", replay)

    def test_custom_repair_stays_domain_authored(self) -> None:
        v1 = self._dataset("special_case", "custom")
        replay = (v1 / "015_replay.sql").read_text(encoding="utf-8")
        self.assertIn("custom replay is domain-owned", replay)
        with self.assertRaises(ValueError):
            generate_silver_repair_scripts(
                project_root=self.root,
                source_id="fleet_mssql",
                dataset_id="special_case",
                candidate_version="v2",
            )

        plan = build_repair_plan(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="special_case",
            problem="silver",
        )
        self.assertTrue(any("CUSTOM repair remains domain-authored" in note for note in plan.notes))
        self.assertFalse(plan.active_production_overwrite)

    def test_bounded_repair_warning_is_explicit(self) -> None:
        self._dataset("orders", "scd2")
        result = generate_silver_repair_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="orders",
            candidate_version="v2",
            requested_from="2026-09-05 00:00:00",
            requested_to="2026-09-06 00:00:00",
        )
        readme = (result.destination / "README.md").read_text(encoding="utf-8")
        self.assertIn("correct baseline outside the requested range", readme)


if __name__ == "__main__":
    unittest.main()
