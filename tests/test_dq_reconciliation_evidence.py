from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.control_plan import build_control_plan
from enterprise_snowflake_framework.init_project import initialize_project
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


class DataQualityReconciliationEvidenceTests(unittest.TestCase):
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

    def _control_sql(self) -> str:
        return (
            self.root / "control_plane" / "sql" / "080_data_quality_reconciliation.sql"
        ).read_text(encoding="utf-8")

    def test_fresh_project_has_dq_reconciliation_control_contract(self) -> None:
        sql_path = self.root / "control_plane" / "sql" / "080_data_quality_reconciliation.sql"
        self.assertTrue(sql_path.is_file())
        sql = sql_path.read_text(encoding="utf-8")

        for expected in (
            "CONTROL.DQ_RESULT",
            "CONTROL.RECONCILIATION_RESULT",
            "CONTROL.RECORD_DQ_RESULT",
            "CONTROL.RECORD_RECONCILIATION_RESULT",
            "CONTROL.DQ_LATEST_RUN_V",
            "CONTROL.RECONCILIATION_ACTIVE_STAGE_V",
            "CONTROL.DATASET_QUALITY_STATUS_V",
            "CONTROL.DATASET_QUALITY_DETAIL_V",
            "CONTROL.EVALUATE_QUALITY_INCIDENTS",
            "CONTROL.EVALUATE_QUALITY_INCIDENTS_TASK",
            "DQ_FAILURE",
            "RECONCILIATION_FAILURE",
            "DQ_STATUS",
            "RECONCILIATION_STATUS",
        ):
            self.assertIn(expected, sql)

        self.assertIn("USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE = 'XSMALL'", sql)
        self.assertIn("SCHEDULE = '1 MINUTE'", sql)
        self.assertIn("-- ALTER TASK CONTROL.EVALUATE_QUALITY_INCIDENTS_TASK RESUME;", sql)
        self.assertNotIn("APPLY_GENERIC", sql)
        self.assertNotIn("EXECUTE IMMEDIATE", sql)

        manifest = (self.root / "control_plane" / "deploy_manifest.txt").read_text(encoding="utf-8")
        self.assertIn("control_plane/sql/080_data_quality_reconciliation.sql", manifest)
        self.assertTrue(build_control_plan(self.root).ready)

    def test_record_apis_fail_closed_for_unknown_status_or_severity(self) -> None:
        sql = self._control_sql()
        self.assertIn("UPPER(COALESCE(:P_STATUS, '')) IN ('PASS', 'FAIL')", sql)
        self.assertIn("'INVALID'", sql)
        self.assertIn("UPPER(COALESCE(:P_CHECK_SEVERITY, '')) = 'WARN'", sql)
        self.assertIn("UPPER(STATUS) <> 'PASS'", sql)
        self.assertNotIn("UPPER(STATUS) = 'FAIL' AND UPPER(CHECK_SEVERITY)", sql)

    def test_active_version_reconciliation_beats_newer_unversioned_evidence_for_same_stage(self) -> None:
        sql = self._control_sql()
        start = sql.index("CREATE OR REPLACE VIEW CONTROL.RECONCILIATION_ACTIVE_STAGE_V")
        end = sql.index("CREATE OR REPLACE VIEW CONTROL.DATASET_QUALITY_STATUS_V")
        active_view = sql[start:end]
        self.assertIn("WHERE R.VERSION IS NULL OR R.VERSION = D.ACTIVE_VERSION", active_view)
        self.assertLess(
            active_view.index("IFF(R.VERSION = D.ACTIVE_VERSION, 1, 0) DESC"),
            active_view.index("R.CHECKED_AT DESC"),
        )

    def test_quality_detail_view_is_evidence_not_rule_metadata(self) -> None:
        sql = self._control_sql()
        start = sql.index("CREATE OR REPLACE VIEW CONTROL.DATASET_QUALITY_DETAIL_V")
        end = sql.index("CREATE OR REPLACE PROCEDURE CONTROL.EVALUATE_QUALITY_INCIDENTS")
        detail = sql[start:end]
        self.assertIn("'DQ' AS EVIDENCE_TYPE", detail)
        self.assertIn("'RECONCILIATION' AS EVIDENCE_TYPE", detail)
        self.assertIn("FROM CONTROL.DQ_RESULT", detail)
        self.assertIn("FROM CONTROL.RECONCILIATION_RESULT", detail)
        self.assertNotIn("RULE_SQL", detail)

    def test_scd2_validation_is_deployed_dataset_local_evidence(self) -> None:
        destination = scaffold_pipeline(
            project_root=self.root,
            source_id="fleet_mssql",
            pattern="scd2",
            dataset_id="customer",
        ).destination
        validate_sql = (destination / "020_validate.sql").read_text(encoding="utf-8")
        task_sql = (destination / "030_task.sql").read_text(encoding="utf-8")
        deploy = (destination / "deploy_manifest.fragment.txt").read_text(encoding="utf-8")

        self.assertIn("CREATE OR REPLACE PROCEDURE SILVER.VALIDATE_FLEET_MSSQL_CUSTOMER_V1", validate_sql)
        self.assertIn("INSERT INTO CONTROL.DQ_RESULT", validate_sql)
        self.assertIn("multiple_active_rows", validate_sql)
        self.assertIn("null_business_key", validate_sql)
        self.assertIn("overlapping_effective_periods", validate_sql)
        self.assertNotIn("SELECT RULE_SQL", validate_sql)
        self.assertNotIn("EXECUTE IMMEDIATE", validate_sql)

        self.assertIn("CALL SILVER.APPLY_FLEET_MSSQL_CUSTOMER_V1();", task_sql)
        self.assertIn("CALL SILVER.VALIDATE_FLEET_MSSQL_CUSTOMER_V1();", task_sql)
        self.assertIn("AS\nBEGIN", task_sql)
        self.assertLess(deploy.index("020_validate.sql"), deploy.index("030_task.sql"))

    def test_candidate_dq_evidence_remains_version_specific(self) -> None:
        scaffold_pipeline(
            project_root=self.root,
            source_id="fleet_mssql",
            pattern="scd2",
            dataset_id="customer",
        )
        candidate = scaffold_version(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            version="v2",
        ).destination
        sql = (candidate / "020_validate.sql").read_text(encoding="utf-8")
        task = (candidate / "030_task.sql").read_text(encoding="utf-8")

        self.assertIn("'v2'", sql)
        self.assertIn("VALIDATE_FLEET_MSSQL_CUSTOMER_V2", sql)
        self.assertIn("VALIDATE_FLEET_MSSQL_CUSTOMER_V2", task)
        control = self._control_sql()
        self.assertIn("Q.VERSION = D.ACTIVE_VERSION", control)
        self.assertIn(
            "candidate DQ evidence",
            (self.root / "operations" / "reconciliation" / "README.md").read_text(
                encoding="utf-8"
            ),
        )

    def test_reconciliation_guidance_does_not_assume_count_equality(self) -> None:
        readme = (self.root / "operations" / "reconciliation" / "README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Do not assume raw row counts should always match", readme)
        self.assertIn("CONTROL.RECORD_RECONCILIATION_RESULT", readme)
        self.assertIn("SOURCE_TO_BRONZE", readme)
        self.assertIn("candidate", readme.lower())
        self.assertIn("does not decide the repair automatically", readme)

    def test_old_domain_gets_migration_but_manifest_is_not_rewritten(self) -> None:
        manifest = self.root / "control_plane" / "deploy_manifest.txt"
        old_manifest = manifest.read_text(encoding="utf-8").replace(
            "control_plane/sql/080_data_quality_reconciliation.sql\n", ""
        )
        manifest.write_text(old_manifest, encoding="utf-8")
        migration = self.root / "control_plane" / "sql" / "080_data_quality_reconciliation.sql"
        reconciliation_readme = self.root / "operations" / "reconciliation" / "README.md"
        migration.unlink()
        reconciliation_readme.unlink()

        initialize_project(self.root)

        self.assertEqual(old_manifest, manifest.read_text(encoding="utf-8"))
        self.assertTrue(migration.is_file())
        self.assertTrue(reconciliation_readme.is_file())
        plan = build_control_plan(self.root)
        self.assertFalse(plan.ready)
        self.assertEqual(
            ("control_plane/sql/080_data_quality_reconciliation.sql",),
            plan.missing_from_manifest,
        )


if __name__ == "__main__":
    unittest.main()
