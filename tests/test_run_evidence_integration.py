from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.control_plan import build_control_plan
from enterprise_snowflake_framework.init_project import initialize_project


class RunEvidenceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(self.root)

    def test_fresh_project_has_end_to_end_run_evidence_starters(self) -> None:
        control_sql = self.root / "control_plane" / "sql" / "060_run_evidence_api.sql"
        metrics_sql = self.root / "control_plane" / "sql" / "110_pipeline_execution_metrics.sql"
        dbt_macro = self.root / "dbt" / "macros" / "esf_observability.sql"
        dbt_project = self.root / "dbt" / "dbt_project.yml"
        ingestion_doc = self.root / "ingestion" / "RUN_EVIDENCE.md"
        ingestion_example = self.root / "ingestion" / "examples" / "run_evidence.sql"

        for path in (control_sql, metrics_sql, dbt_macro, dbt_project, ingestion_doc, ingestion_example):
            self.assertTrue(path.is_file(), path)

        manifest = (self.root / "control_plane" / "deploy_manifest.txt").read_text(encoding="utf-8")
        self.assertIn("control_plane/sql/060_run_evidence_api.sql", manifest)
        self.assertIn("control_plane/sql/110_pipeline_execution_metrics.sql", manifest)
        self.assertTrue(build_control_plan(self.root).ready)

        project_text = dbt_project.read_text(encoding="utf-8")
        self.assertIn("on-run-end:", project_text)
        self.assertIn("esf_record_dbt_results(results)", project_text)

    def test_control_migration_exposes_ledger_api_without_becoming_ingestion_runtime(self) -> None:
        sql = (
            self.root / "control_plane" / "sql" / "060_run_evidence_api.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("CONTROL.BEGIN_INGESTION_RUN", sql)
        self.assertIn("CONTROL.COMPLETE_INGESTION_RUN", sql)
        self.assertIn("CONTROL.FAIL_INGESTION_RUN", sql)
        self.assertIn("WHERE NOT EXISTS", sql)
        self.assertIn("INVOCATION_ID", sql)
        self.assertIn("RESOURCE_UNIQUE_ID", sql)
        self.assertNotIn("CREATE TASK", sql)
        self.assertNotIn("SYSTEM$STREAM_HAS_DATA", sql)

    def test_pipeline_metrics_migration_preserves_native_runtime_boundaries(self) -> None:
        sql = (
            self.root / "control_plane" / "sql" / "110_pipeline_execution_metrics.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("CONTROL.PIPELINE_EXECUTION_METRICS_V", sql)
        self.assertIn("METRICS_CONTRACT_VERSION", sql)
        self.assertIn("DML_QUERY_ID", sql)
        self.assertNotIn("DYNAMIC_TABLE_REFRESH_HISTORY", sql)
        self.assertNotIn("CREATE TASK", sql)
        self.assertNotIn("EXECUTE IMMEDIATE", sql)

    def test_dbt_macro_uses_documented_result_evidence_and_explicit_dataset_mapping(self) -> None:
        macro = (
            self.root / "dbt" / "macros" / "esf_observability.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("results | selectattr", macro)
        self.assertIn("res.status", macro)
        self.assertIn("res.execution_time", macro)
        self.assertIn("res.adapter_response", macro)
        self.assertIn("res.node.config.meta", macro)
        self.assertIn("esf_dataset_id", macro)
        self.assertIn("CONTROL.DBT_RUN", macro)
        self.assertIn("CONTROL.PIPELINE_RUN", macro)
        self.assertIn("invocation_id", macro)
        self.assertIn("ESF_PROJECT_GIT_SHA", macro)
        self.assertIn("raw_status == 'success'", macro)
        self.assertIn("esf_status = 'FAILED'", macro)

    def test_ingestion_guidance_preserves_connector_ownership(self) -> None:
        doc = (self.root / "ingestion" / "RUN_EVIDENCE.md").read_text(encoding="utf-8")
        example = (
            self.root / "ingestion" / "examples" / "run_evidence.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("does not schedule Openflow, Snowpipe, Kafka", doc)
        self.assertIn("Do not recreate Kafka offsets", doc)
        self.assertIn("BEGIN_INGESTION_RUN", example)
        self.assertIn("COMPLETE_INGESTION_RUN", example)
        self.assertIn("FAIL_INGESTION_RUN", example)

    def test_old_repo_upgrade_adds_files_but_never_enables_them_implicitly(self) -> None:
        manifest = self.root / "control_plane" / "deploy_manifest.txt"
        old_manifest = "\n".join(
            [
                "control_plane/sql/001_objects.sql",
                "control_plane/sql/010_observability_views.sql",
                "control_plane/sql/020_refresh_health.sql",
                "control_plane/sql/030_sla_incident_lifecycle.sql",
                "control_plane/sql/040_health_task.sql",
                "control_plane/sql/050_dataset_lifecycle_status.sql",
                "",
            ]
        )
        manifest.write_text(old_manifest, encoding="utf-8")

        old_dbt_project = """name: 'transport'\nversion: '1.0.0'\nconfig-version: 2\nprofile: 'transport'\nmodel-paths: ['models']\n"""
        dbt_project = self.root / "dbt" / "dbt_project.yml"
        dbt_project.write_text(old_dbt_project, encoding="utf-8")

        (self.root / "control_plane" / "sql" / "060_run_evidence_api.sql").unlink()
        (self.root / "control_plane" / "sql" / "070_enterprise_health_export.sql").unlink()
        (self.root / "control_plane" / "sql" / "080_data_quality_reconciliation.sql").unlink()
        (self.root / "control_plane" / "sql" / "090_dataset_execution_model.sql").unlink()
        (self.root / "control_plane" / "sql" / "100_dynamic_table_observability.sql").unlink()
        (self.root / "control_plane" / "sql" / "110_pipeline_execution_metrics.sql").unlink()
        (self.root / "dbt" / "macros" / "esf_observability.sql").unlink()
        (self.root / "dbt" / "README.md").unlink()
        (self.root / "ingestion" / "RUN_EVIDENCE.md").unlink()
        (self.root / "ingestion" / "examples" / "run_evidence.sql").unlink()

        initialize_project(self.root)

        self.assertEqual(old_manifest, manifest.read_text(encoding="utf-8"))
        self.assertEqual(old_dbt_project, dbt_project.read_text(encoding="utf-8"))
        self.assertTrue((self.root / "control_plane" / "sql" / "060_run_evidence_api.sql").is_file())
        self.assertTrue((self.root / "control_plane" / "sql" / "070_enterprise_health_export.sql").is_file())
        self.assertTrue((self.root / "control_plane" / "sql" / "080_data_quality_reconciliation.sql").is_file())
        self.assertTrue((self.root / "control_plane" / "sql" / "090_dataset_execution_model.sql").is_file())
        self.assertTrue((self.root / "control_plane" / "sql" / "100_dynamic_table_observability.sql").is_file())
        self.assertTrue((self.root / "control_plane" / "sql" / "110_pipeline_execution_metrics.sql").is_file())
        self.assertTrue((self.root / "dbt" / "macros" / "esf_observability.sql").is_file())
        self.assertTrue((self.root / "ingestion" / "RUN_EVIDENCE.md").is_file())

        plan = build_control_plan(self.root)
        self.assertFalse(plan.ready)
        self.assertEqual(
            (
                "control_plane/sql/060_run_evidence_api.sql",
                "control_plane/sql/070_enterprise_health_export.sql",
                "control_plane/sql/080_data_quality_reconciliation.sql",
                "control_plane/sql/090_dataset_execution_model.sql",
                "control_plane/sql/100_dynamic_table_observability.sql",
                "control_plane/sql/110_pipeline_execution_metrics.sql",
            ),
            plan.missing_from_manifest,
        )
        self.assertNotIn("esf_record_dbt_results", dbt_project.read_text(encoding="utf-8"))

    def test_dbt_readme_requires_explicit_one_to_one_gold_mapping(self) -> None:
        text = (self.root / "dbt" / "README.md").read_text(encoding="utf-8")
        self.assertIn("esf_dataset_id: fleet_mssql.customer", text)
        self.assertIn("Do not assign `esf_dataset_id` to a business mart that combines several", text)
        self.assertIn("does not infer a Gold business-event timestamp", text)


if __name__ == "__main__":
    unittest.main()
