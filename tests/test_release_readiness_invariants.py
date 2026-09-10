from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.control_plan import build_control_plan
from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.pipeline_model import build_names
from enterprise_snowflake_framework.pipeline_operations import render_release_sql
from enterprise_snowflake_framework.scaffold import scaffold_pipeline
from enterprise_snowflake_framework.source_management import add_source
from enterprise_snowflake_framework.versioning import generate_release_scripts, scaffold_version


RAW = """schema_version: 2
contract:
  source_system: fleet_mssql
  entity: customer
  grain: one row per source change
  business_key: [id]
  source_timestamp: source_updated_at
  columns:
    - {name: id, type: VARCHAR, nullable: false}
    - {name: value, type: VARCHAR, nullable: true}
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


class ReleaseReadinessInvariantTests(unittest.TestCase):
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
        self.v2 = scaffold_version(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            version="v2",
        ).destination

    def test_control_migration_is_append_only_release_evidence_not_runtime_engine(self) -> None:
        migration = self.root / "control_plane" / "sql" / "120_release_readiness.sql"
        self.assertTrue(migration.is_file())
        sql = migration.read_text(encoding="utf-8")
        for name in (
            "CONTROL.RELEASE_RUN",
            "CONTROL.DATASET_VERSION_INVARIANT_V",
            "CONTROL.CANDIDATE_COMPARISON_STATUS_V",
            "CONTROL.CANDIDATE_RUNTIME_STATUS_V",
            "CONTROL.RELEASE_READINESS_V",
            "CONTROL.RELEASE_RUN_LATEST_V",
        ):
            self.assertIn(name, sql)
        self.assertIn("ACTIVE_STATUS_COUNT <> 1", sql)
        self.assertIn("DEPLOYED_STATUS_COUNT > 1", sql)
        self.assertIn("CANDIDATE_VERSION = ACTIVE_VERSION", sql)
        self.assertIn("MIN(VALIDATED_AT) AS OLDEST_VALIDATED_AT", sql)
        self.assertIn("Q.CHECKED_AT < R.RUNTIME_EVIDENCE_AT", sql)
        self.assertIn("C.OLDEST_VALIDATED_AT < R.RUNTIME_EVIDENCE_AT", sql)
        self.assertIn("at least one latest comparison check is older than latest runtime evidence", sql)
        self.assertIn("THEN 'REVIEW_REQUIRED'", sql)
        self.assertNotIn("EXECUTE IMMEDIATE", sql)
        self.assertNotIn("ALTER TASK", sql)
        self.assertNotIn("ALTER DYNAMIC TABLE", sql)

        manifest = (self.root / "control_plane" / "deploy_manifest.txt").read_text(encoding="utf-8")
        self.assertTrue(manifest.rstrip().endswith("control_plane/sql/120_release_readiness.sql"))
        self.assertTrue(build_control_plan(self.root).ready)

    def test_candidate_registration_blocks_second_candidate_before_pointer_update(self) -> None:
        register = (self.v2 / "040_register.sql").read_text(encoding="utf-8")
        self.assertIn("E_CANDIDATE_CONFLICT", register)
        self.assertIn("Another candidate is already registered", register)
        self.assertIn("V_OTHER_DEPLOYED_COUNT", register)
        self.assertIn("V_CANDIDATE_VERSION <> 'v2'", register)
        self.assertIn("V_ACTIVE_VERSION = 'v2'", register)
        self.assertIn("D.CANDIDATE_VERSION = 'v2'", register)
        self.assertLess(register.index("E_CANDIDATE_CONFLICT"), register.index("MERGE INTO CONTROL.DATASET D"))

    def test_release_bundle_has_read_only_preview_hard_guards_audit_and_postflight(self) -> None:
        result = generate_release_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            from_version="v1",
            to_version="v2",
        )
        self.assertEqual(
            {"README.md", "preflight.sql", "activate.sql", "rollback.sql", "postflight.sql"},
            {path.name for path in result.files},
        )
        preflight = (result.destination / "preflight.sql").read_text(encoding="utf-8")
        activate = (result.destination / "activate.sql").read_text(encoding="utf-8")
        rollback = (result.destination / "rollback.sql").read_text(encoding="utf-8")
        postflight = (result.destination / "postflight.sql").read_text(encoding="utf-8")

        self.assertIn("CONTROL.RELEASE_READINESS_V", preflight)
        self.assertIn("REQUESTED_EDGE_STATUS", preflight)
        self.assertNotIn("UPDATE ", preflight)
        self.assertNotIn("INSERT INTO", preflight)
        self.assertNotIn("ALTER ", preflight)

        self.assertIn("INSERT INTO CONTROL.RELEASE_RUN", activate)
        self.assertIn("FROM CONTROL.RELEASE_READINESS_V", activate)
        self.assertIn("E_RELEASE_BLOCKED", activate)
        self.assertIn("E_REVIEW_REQUIRED", activate)
        self.assertIn("V_CURRENT_ACTIVE <> 'v1'", activate)
        self.assertIn("V_CURRENT_CANDIDATE <> 'v2'", activate)
        self.assertIn("CREATE OR REPLACE VIEW SILVER.FLEET_MSSQL_CUSTOMER_HISTORY COPY GRANTS", activate)
        self.assertIn("INFORMATION_SCHEMA.VIEWS", activate)
        self.assertIn("FAILED_PHASE = :V_PHASE", activate)
        self.assertIn("POSTFLIGHT_STATUS = 'PASS'", activate)
        self.assertIn("WHEN OTHER THEN", activate)
        self.assertIn("RAISE;", activate)
        self.assertLess(
            activate.index("CREATE OR REPLACE VIEW SILVER.FLEET_MSSQL_CUSTOMER_HISTORY COPY GRANTS"),
            activate.index("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V1_TASK SUSPEND"),
        )

        self.assertIn("ACTION, FROM_VERSION, TO_VERSION", rollback)
        self.assertIn("'ROLLBACK', 'v2', 'v1'", rollback)
        self.assertIn("V_CURRENT_CANDIDATE IS NOT NULL", rollback)
        self.assertIn("UPPER(COALESCE(V_TARGET_STATUS, '')) <> 'RETIRED'", rollback)
        self.assertIn("CONTROL.RELEASE_RUN_LATEST_V", postflight)
        self.assertIn("CONTROL.DATASET_VERSION_INVARIANT_V", postflight)

    def test_review_required_acceptance_is_explicit_and_reasoned(self) -> None:
        old = build_names(
            source_id="fleet_mssql",
            dataset_id="customer",
            pattern="scd2",
            entity="customer",
            version="v1",
        )
        new = build_names(
            source_id="fleet_mssql",
            dataset_id="customer",
            pattern="scd2",
            entity="customer",
            version="v2",
        )
        with self.assertRaisesRegex(ValueError, "operator_reason is required"):
            render_release_sql("scd2", old, new, allow_review_required=True)

        activate, _ = render_release_sql(
            "scd2",
            old,
            new,
            allow_review_required=True,
            operator_reason="History delta reviewed; expected retention change",
        )
        self.assertIn("TRUE, 'History delta reviewed; expected retention change'", activate)
        self.assertIn("V_READINESS_STATUS = 'REVIEW_REQUIRED' AND NOT TRUE", activate)

    def test_release_ownership_unit_is_never_rewritten(self) -> None:
        result = generate_release_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            from_version="v1",
            to_version="v2",
        )
        marker = result.destination / "activate.sql"
        marker.write_text("-- DOMAIN REVIEWED RELEASE\n", encoding="utf-8")
        repeated = generate_release_scripts(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            from_version="v1",
            to_version="v2",
            allow_review_required=True,
            operator_reason="later request must not rewrite ownership unit",
        )
        self.assertFalse(repeated.created)
        self.assertEqual("-- DOMAIN REVIEWED RELEASE\n", marker.read_text(encoding="utf-8"))

    def test_old_domain_materializes_120_without_rewriting_manifest(self) -> None:
        manifest = self.root / "control_plane" / "deploy_manifest.txt"
        old_manifest = manifest.read_text(encoding="utf-8").replace(
            "control_plane/sql/120_release_readiness.sql\n", ""
        )
        manifest.write_text(old_manifest, encoding="utf-8")
        migration = self.root / "control_plane" / "sql" / "120_release_readiness.sql"
        migration.unlink()

        initialize_project(self.root)

        self.assertEqual(old_manifest, manifest.read_text(encoding="utf-8"))
        self.assertTrue(migration.is_file())
        plan = build_control_plan(self.root)
        self.assertFalse(plan.ready)
        self.assertEqual(("control_plane/sql/120_release_readiness.sql",), plan.missing_from_manifest)


if __name__ == "__main__":
    unittest.main()
