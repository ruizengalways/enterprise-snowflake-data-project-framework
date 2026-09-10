from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.pipeline_sql import build_names, render_apply_sql


CONTRACT = {
    "entity": "customer",
    "business_key": ["id"],
    "source_timestamp": "source_updated_at",
    "columns": [
        {"name": "id", "type": "VARCHAR", "nullable": False},
        {"name": "value", "type": "VARCHAR", "nullable": True},
        {"name": "source_updated_at", "type": "TIMESTAMP_NTZ", "nullable": False},
        {"name": "source_sequence", "type": "NUMBER", "nullable": False},
        {"name": "source_operation", "type": "VARCHAR", "nullable": False},
        {"name": "ingested_at", "type": "TIMESTAMP_LTZ", "nullable": False},
    ],
    "change_semantics": {
        "mode": "cdc",
        "operation_column": "source_operation",
        "sequence_column": "source_sequence",
        "delete_semantics": "tombstone",
        "delete_values": ["D"],
    },
    "ordering_columns": ["source_updated_at", "source_sequence"],
    "idempotency_key": ["id", "source_sequence"],
}


def sql_for(pattern: str) -> str:
    names = build_names(
        source_id="fleet_mssql",
        dataset_id="customer",
        pattern=pattern,
        entity="customer",
        version="v1",
    )
    return render_apply_sql(pattern, names, CONTRACT)


class PipelineMetricsContractTests(unittest.TestCase):
    def test_all_explicit_apply_patterns_write_the_same_canonical_columns(self) -> None:
        for pattern in ("append", "full_refresh", "scd1", "scd2"):
            with self.subTest(pattern=pattern):
                sql = sql_for(pattern)
                self.assertIn("ROWS_AFFECTED = :V_ROWS_AFFECTED", sql)
                self.assertIn("AFFECTED_BUSINESS_KEYS = :V_AFFECTED_BUSINESS_KEYS", sql)
                self.assertIn("DML_QUERY_ID = :V_DML_QUERY_ID", sql)
                self.assertIn("QUERY_ID = :V_DML_QUERY_ID", sql)
                self.assertIn("METRICS_CONTRACT_VERSION = 1", sql)
                self.assertNotIn("QUERY_ID = LAST_QUERY_ID()", sql)

        for pattern in ("append", "full_refresh", "scd1"):
            with self.subTest(primary_capture=pattern):
                sql = sql_for(pattern)
                self.assertIn("V_ROWS_AFFECTED := SQLROWCOUNT;", sql)
                self.assertIn("V_DML_QUERY_ID := SQLID;", sql)

        scd2 = sql_for("scd2")
        self.assertIn("V_HISTORY_ROWS_REBUILT := SQLROWCOUNT;", scd2)
        self.assertIn("V_HISTORY_REBUILD_QUERY_ID := SQLID;", scd2)
        self.assertIn("V_ROWS_AFFECTED := V_HISTORY_ROWS_REBUILT;", scd2)
        self.assertIn("V_DML_QUERY_ID := V_HISTORY_REBUILD_QUERY_ID;", scd2)

    def test_scd1_never_labels_total_merge_rowcount_as_rows_updated(self) -> None:
        sql = sql_for("scd1")
        self.assertIn("SQLROWCOUNT is total MERGE rows affected, not update-only", sql)
        self.assertIn("'merge_rows_affected', V_ROWS_AFFECTED", sql)
        self.assertNotIn("V_ROWS_UPDATED := SQLROWCOUNT", sql)
        self.assertNotIn("V_ROWS_INSERTED := SQLROWCOUNT", sql)
        self.assertNotIn("V_ROWS_DELETED := SQLROWCOUNT", sql)

    def test_append_only_populates_unambiguous_legacy_insert_count(self) -> None:
        sql = sql_for("append")
        self.assertIn("V_ROWS_INSERTED := V_ROWS_AFFECTED;", sql)
        self.assertIn("V_ROWS_UPDATED := 0;", sql)
        self.assertIn("V_ROWS_DELETED := 0;", sql)
        self.assertIn("'output_rows_inserted', V_ROWS_AFFECTED", sql)

    def test_full_refresh_does_not_invent_update_or_delete_breakdown(self) -> None:
        sql = sql_for("full_refresh")
        self.assertIn("V_ROWS_INSERTED := V_ROWS_AFFECTED;", sql)
        self.assertIn("'snapshot_rows_written', V_ROWS_AFFECTED", sql)
        self.assertNotIn("V_ROWS_UPDATED := SQLROWCOUNT", sql)
        self.assertNotIn("V_ROWS_DELETED := SQLROWCOUNT", sql)

    def test_scd2_keeps_physical_work_in_pattern_specific_metrics(self) -> None:
        sql = sql_for("scd2")
        self.assertIn("V_EVENTS_INSERTED := SQLROWCOUNT;", sql)
        self.assertIn("V_EVENTS_INSERT_QUERY_ID := SQLID;", sql)
        self.assertIn("V_HISTORY_ROWS_DELETED := SQLROWCOUNT;", sql)
        self.assertIn("V_HISTORY_DELETE_QUERY_ID := SQLID;", sql)
        self.assertIn("V_HISTORY_ROWS_REBUILT := SQLROWCOUNT;", sql)
        self.assertIn("V_HISTORY_REBUILD_QUERY_ID := SQLID;", sql)
        self.assertIn("V_ROWS_AFFECTED := V_HISTORY_ROWS_REBUILT;", sql)
        self.assertIn("V_DML_QUERY_ID := V_HISTORY_REBUILD_QUERY_ID;", sql)
        self.assertIn("'events_inserted', V_EVENTS_INSERTED", sql)
        self.assertIn("'history_rows_deleted', V_HISTORY_ROWS_DELETED", sql)
        self.assertIn("'history_rows_rebuilt', V_HISTORY_ROWS_REBUILT", sql)
        self.assertNotIn("V_ROWS_UPDATED := SQLROWCOUNT", sql)

    def test_control_migration_adds_versioned_canonical_metrics_without_rewriting_001(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "enterprise-snowflake-transport-analytics"
            initialize_project(root)
            migration = root / "control_plane" / "sql" / "110_pipeline_execution_metrics.sql"
            self.assertTrue(migration.is_file())
            sql = migration.read_text(encoding="utf-8")
            self.assertIn("ADD COLUMN IF NOT EXISTS METRICS_CONTRACT_VERSION", sql)
            self.assertIn("ADD COLUMN IF NOT EXISTS ROWS_AFFECTED", sql)
            self.assertIn("ADD COLUMN IF NOT EXISTS AFFECTED_BUSINESS_KEYS", sql)
            self.assertIn("ADD COLUMN IF NOT EXISTS DML_QUERY_ID", sql)
            self.assertIn("ADD COLUMN IF NOT EXISTS METRICS VARIANT", sql)
            self.assertIn("CREATE VIEW CONTROL.PIPELINE_EXECUTION_METRICS_V", sql)
            self.assertIn("LEGACY_ROWS_UPDATED", sql)

            manifest = (root / "control_plane" / "deploy_manifest.txt").read_text(encoding="utf-8")
            self.assertTrue(manifest.rstrip().endswith("control_plane/sql/110_pipeline_execution_metrics.sql"))

            original = (root / "control_plane" / "sql" / "001_objects.sql").read_text(encoding="utf-8")
            self.assertIn("ROWS_UPDATED NUMBER", original)
            self.assertNotIn("METRICS_CONTRACT_VERSION", original)


if __name__ == "__main__":
    unittest.main()
