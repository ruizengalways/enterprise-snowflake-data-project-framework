from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.control_plan import KNOWN_CONTROL_SQL, build_control_plan
from enterprise_snowflake_framework.init_project import initialize_project


class DynamicTableObservabilityEnrichmentTests(unittest.TestCase):
    def _project(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(root)
        return tmp, root

    def test_fresh_project_appends_migration_140_and_is_ready(self) -> None:
        _, root = self._project()
        migration = root / "control_plane" / "sql" / "140_dynamic_table_observability_enrichment.sql"
        manifest = (root / "control_plane" / "deploy_manifest.txt").read_text(encoding="utf-8")

        self.assertTrue(migration.is_file())
        self.assertTrue(manifest.rstrip().endswith("control_plane/sql/140_dynamic_table_observability_enrichment.sql"))
        self.assertEqual("control_plane/sql/140_dynamic_table_observability_enrichment.sql", KNOWN_CONTROL_SQL[-1])
        self.assertTrue(build_control_plan(root).ready)

    def test_released_migration_100_remains_the_original_boundary(self) -> None:
        _, root = self._project()
        migration100 = (
            root / "control_plane" / "sql" / "100_dynamic_table_observability.sql"
        ).read_text(encoding="utf-8")
        migration140 = (
            root / "control_plane" / "sql" / "140_dynamic_table_observability_enrichment.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY", migration100)
        self.assertNotIn("INPUTS_WITH_CHANGED_DATA", migration100)
        self.assertNotIn("INFORMATION_SCHEMA.DYNAMIC_TABLES", migration100)
        self.assertIn("INPUTS_WITH_CHANGED_DATA", migration140)
        self.assertIn("INFORMATION_SCHEMA.DYNAMIC_TABLES", migration140)

    def test_enrichment_uses_native_refresh_and_scheduling_diagnostics(self) -> None:
        _, root = self._project()
        sql = (
            root / "control_plane" / "sql" / "140_dynamic_table_observability_enrichment.sql"
        ).read_text(encoding="utf-8")

        for field in (
            "REFRESH_ACTION",
            "REFRESH_TRIGGER",
            "REINIT_REASON",
            "STATISTICS",
            "INPUTS_WITH_CHANGED_DATA",
            "TARGET_LAG_SEC",
            "TARGET_LAG_TYPE",
            "SCHEDULING_STATE",
            "SCHEDULING_REASON_CODE",
            "SCHEDULING_REASON_MESSAGE",
            "MEAN_LAG_SEC",
            "MAXIMUM_LAG_SEC",
            "TIME_ABOVE_TARGET_LAG_SEC",
            "TIME_WITHIN_TARGET_LAG_RATIO",
            "LATEST_DATA_TIMESTAMP",
            "LAST_COMPLETED_REFRESH_STATE",
            "EXECUTING_REFRESH_QUERY_ID",
        ):
            self.assertIn(field, sql)

        for statistic in (
            "numInsertedRows",
            "numDeletedRows",
            "numCopiedRows",
            "numAddedPartitions",
            "numRemovedPartitions",
            "queuedTimeMs",
            "compilationTimeMs",
            "executionTimeMs",
        ):
            self.assertIn(statistic, sql)

    def test_running_refresh_wins_over_previous_completed_state(self) -> None:
        _, root = self._project()
        sql = (
            root / "control_plane" / "sql" / "140_dynamic_table_observability_enrichment.sql"
        ).read_text(encoding="utf-8")
        running = "WHEN R.STATE = 'EXECUTING' OR C.EXECUTING_REFRESH_QUERY_ID IS NOT NULL THEN 'RUNNING'"
        success = "WHEN COALESCE(R.STATE, C.LAST_COMPLETED_REFRESH_STATE) IN ('SUCCEEDED', 'SKIPPED') THEN 'SUCCESS'"
        self.assertLess(sql.index(running), sql.index(success))

    def test_enrichment_reuses_existing_views_and_never_fabricates_runtime_rows(self) -> None:
        _, root = self._project()
        sql = (
            root / "control_plane" / "sql" / "140_dynamic_table_observability_enrichment.sql"
        ).read_text(encoding="utf-8")
        executable = "\n".join(
            line for line in sql.splitlines() if not line.lstrip().startswith("--")
        )

        self.assertIn("CREATE OR REPLACE VIEW CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V COPY GRANTS", sql)
        self.assertIn("CREATE OR REPLACE VIEW CONTROL.DATASET_OBSERVABILITY_V COPY GRANTS", sql)
        self.assertEqual(2, executable.count("CREATE OR REPLACE VIEW CONTROL."))
        self.assertNotIn("INSERT INTO CONTROL.PIPELINE_RUN", sql)
        self.assertNotIn("CREATE TABLE", executable)
        self.assertNotIn("ACCOUNT_USAGE", sql)

    def test_unified_view_exposes_only_compact_dynamic_table_triage_fields(self) -> None:
        _, root = self._project()
        sql = (
            root / "control_plane" / "sql" / "140_dynamic_table_observability_enrichment.sql"
        ).read_text(encoding="utf-8")
        unified = sql.split("CREATE OR REPLACE VIEW CONTROL.DATASET_OBSERVABILITY_V COPY GRANTS AS", 1)[1]

        for field in (
            "DYNAMIC_TABLE_SCHEDULING_STATE",
            "DYNAMIC_TABLE_SCHEDULING_REASON_CODE",
            "DYNAMIC_TABLE_TARGET_LAG_SECONDS",
            "DYNAMIC_TABLE_MEAN_LAG_SECONDS",
            "DYNAMIC_TABLE_MAXIMUM_LAG_SECONDS",
            "DYNAMIC_TABLE_TIME_ABOVE_TARGET_LAG_SECONDS",
            "DYNAMIC_TABLE_TIME_WITHIN_TARGET_LAG_RATIO",
            "DYNAMIC_TABLE_REFRESH_ACTION",
            "DYNAMIC_TABLE_REFRESH_TRIGGER",
            "DYNAMIC_TABLE_REINIT_REASON",
            "DYNAMIC_TABLE_REFRESH_QUEUED_TIME_MS",
            "DYNAMIC_TABLE_REFRESH_COMPILATION_TIME_MS",
            "DYNAMIC_TABLE_REFRESH_EXECUTION_TIME_MS",
            "DYNAMIC_TABLE_REFRESH_QUERY_ID",
        ):
            self.assertIn(field, unified)
        self.assertNotIn("REFRESH_STATISTICS", unified)
        self.assertNotIn("INPUTS_WITH_CHANGED_DATA", unified)

    def test_old_domain_materializes_140_without_rewriting_manifest(self) -> None:
        _, root = self._project()
        manifest_path = root / "control_plane" / "deploy_manifest.txt"
        current_manifest = manifest_path.read_text(encoding="utf-8")
        old_manifest = current_manifest.replace(
            "control_plane/sql/140_dynamic_table_observability_enrichment.sql\n", ""
        )
        manifest_path.write_text(old_manifest, encoding="utf-8")
        migration = root / "control_plane" / "sql" / "140_dynamic_table_observability_enrichment.sql"
        migration.unlink()

        initialize_project(root)

        self.assertEqual(old_manifest, manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(migration.is_file())
        plan = build_control_plan(root)
        self.assertEqual(
            ("control_plane/sql/140_dynamic_table_observability_enrichment.sql",),
            plan.missing_from_manifest,
        )
        self.assertFalse(plan.ready)


if __name__ == "__main__":
    unittest.main()
