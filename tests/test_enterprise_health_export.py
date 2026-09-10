from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.control_plan import build_control_plan
from enterprise_snowflake_framework.init_project import initialize_project


class EnterpriseHealthExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(self.root)

    def test_fresh_project_exports_stable_domain_health_contract(self) -> None:
        sql_path = self.root / "control_plane" / "sql" / "070_enterprise_health_export.sql"
        quality_path = self.root / "control_plane" / "sql" / "080_data_quality_reconciliation.sql"
        doc_path = self.root / "docs" / "ENTERPRISE_HEALTH_EXPORT.md"
        self.assertTrue(sql_path.is_file())
        self.assertTrue(quality_path.is_file())
        self.assertTrue(doc_path.is_file())

        sql = sql_path.read_text(encoding="utf-8")
        self.assertIn("CREATE OR REPLACE VIEW CONTROL.ENTERPRISE_HEALTH_EXPORT_V", sql)
        self.assertIn("CREATE OR REPLACE VIEW CONTROL.DOMAIN_HEALTH_SUMMARY_V", sql)
        self.assertIn("'TRANSPORT'::VARCHAR AS DOMAIN_CODE", sql)
        self.assertIn("CURRENT_DATABASE() AS DOMAIN_DATABASE", sql)
        self.assertIn("FROM CONTROL.DATASET_HEALTH_V", sql)
        self.assertIn("COUNT_IF(OVERALL_STATUS = 'RED')", sql)
        self.assertIn("SUM(OPEN_INCIDENT_COUNT)", sql)
        self.assertNotIn("INSERT INTO", sql)
        self.assertNotIn("UPDATE CONTROL", sql)
        self.assertNotIn("CREATE TASK", sql)

        quality = quality_path.read_text(encoding="utf-8")
        self.assertIn("DQ_STATUS", quality)
        self.assertIn("RECONCILIATION_STATUS", quality)
        self.assertIn("CREATE OR REPLACE VIEW CONTROL.ENTERPRISE_HEALTH_EXPORT_V", quality)
        self.assertIn("DQ_FAILED_DATASET_COUNT", quality)

        manifest = (self.root / "control_plane" / "deploy_manifest.txt").read_text(encoding="utf-8")
        self.assertIn("control_plane/sql/070_enterprise_health_export.sql", manifest)
        self.assertIn("control_plane/sql/080_data_quality_reconciliation.sql", manifest)
        self.assertTrue(build_control_plan(self.root).ready)

    def test_enterprise_guidance_keeps_cross_domain_layer_read_only(self) -> None:
        text = (self.root / "docs" / "ENTERPRISE_HEALTH_EXPORT.md").read_text(encoding="utf-8")
        self.assertIn("Enterprise monitoring consumes a stable read-only export", text)
        self.assertIn("UNION ALL", text)
        self.assertIn("PROD_TRANSPORT.CONTROL.ENTERPRISE_HEALTH_EXPORT_V", text)
        self.assertIn("Cross-domain roles/grants belong in platform infrastructure", text)
        self.assertIn("remove only that domain's `UNION ALL` branch", text)

    def test_old_domain_upgrade_never_rewrites_manifest(self) -> None:
        manifest = self.root / "control_plane" / "deploy_manifest.txt"
        old_manifest = "\n".join(
            [
                "control_plane/sql/001_objects.sql",
                "control_plane/sql/010_observability_views.sql",
                "control_plane/sql/020_refresh_health.sql",
                "control_plane/sql/030_sla_incident_lifecycle.sql",
                "control_plane/sql/040_health_task.sql",
                "control_plane/sql/050_dataset_lifecycle_status.sql",
                "control_plane/sql/060_run_evidence_api.sql",
                "",
            ]
        )
        manifest.write_text(old_manifest, encoding="utf-8")
        export_sql = self.root / "control_plane" / "sql" / "070_enterprise_health_export.sql"
        quality_sql = self.root / "control_plane" / "sql" / "080_data_quality_reconciliation.sql"
        export_doc = self.root / "docs" / "ENTERPRISE_HEALTH_EXPORT.md"
        export_sql.unlink()
        quality_sql.unlink()
        export_doc.unlink()

        initialize_project(self.root)

        self.assertEqual(old_manifest, manifest.read_text(encoding="utf-8"))
        self.assertTrue(export_sql.is_file())
        self.assertTrue(quality_sql.is_file())
        self.assertTrue(export_doc.is_file())
        plan = build_control_plan(self.root)
        self.assertFalse(plan.ready)
        self.assertEqual(
            (
                "control_plane/sql/070_enterprise_health_export.sql",
                "control_plane/sql/080_data_quality_reconciliation.sql",
                "control_plane/sql/090_dataset_execution_model.sql",
                "control_plane/sql/100_dynamic_table_observability.sql",
                "control_plane/sql/110_pipeline_execution_metrics.sql",
                "control_plane/sql/120_release_readiness.sql",
                "control_plane/sql/130_health_evaluation_cadence.sql",
            ),
            plan.missing_from_manifest,
        )


if __name__ == "__main__":
    unittest.main()
