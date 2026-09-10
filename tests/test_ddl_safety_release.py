from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.migration_model import HistoryRecord, build_migration_plan, load_migrations
from enterprise_snowflake_framework.pipeline_sql import (
    build_names,
    render_apply_sql,
    render_objects_sql,
    render_publish_sql,
    render_release_sql,
    render_replay_sql,
    render_task_sql,
    render_validate_sql,
)


SCD2_CONTRACT = {
    "entity": "customer",
    "business_key": ["id"],
    "source_timestamp": "source_updated_at",
    "columns": [
        {"name": "id", "type": "VARCHAR", "nullable": False},
        {"name": "name", "type": "VARCHAR", "nullable": True},
        {"name": "source_updated_at", "type": "TIMESTAMP_NTZ", "nullable": False},
        {"name": "source_sequence", "type": "NUMBER", "nullable": False},
        {"name": "source_operation", "type": "VARCHAR", "nullable": False},
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


class DdlSafetyReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.v1 = build_names(
            source_id="fleet_mssql",
            dataset_id="customer",
            pattern="scd2",
            entity="customer",
            version="v1",
        )
        self.v2 = build_names(
            source_id="fleet_mssql",
            dataset_id="customer",
            pattern="scd2",
            entity="customer",
            version="v2",
        )

    def test_new_version_owned_persistent_objects_are_create_only(self) -> None:
        objects = render_objects_sql("scd2", self.v2, SCD2_CONTRACT)
        apply_sql = render_apply_sql("scd2", self.v2, SCD2_CONTRACT)
        replay_sql = render_replay_sql("scd2", self.v2, SCD2_CONTRACT)
        validate_sql = render_validate_sql("scd2", self.v2, SCD2_CONTRACT)
        task_sql = render_task_sql("scd2", self.v2, "TRANSPORT")

        self.assertIn("CREATE TABLE SILVER.FLEET_MSSQL_CUSTOMER_V2_EVENTS", objects)
        self.assertIn("CREATE TABLE SILVER.FLEET_MSSQL_CUSTOMER_V2_HISTORY", objects)
        self.assertIn("CREATE VIEW SILVER.FLEET_MSSQL_CUSTOMER_V2_CURRENT", objects)
        self.assertIn("CREATE STREAM BRONZE.FLEET_MSSQL_CUSTOMER_V2_STREAM", objects)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS", objects)
        self.assertNotIn("CREATE STREAM IF NOT EXISTS", objects)
        self.assertNotIn("CREATE OR REPLACE VIEW", objects)

        self.assertIn("CREATE PROCEDURE SILVER.APPLY_FLEET_MSSQL_CUSTOMER_V2", apply_sql)
        self.assertNotIn("CREATE OR REPLACE PROCEDURE SILVER.APPLY_", apply_sql)
        self.assertIn("CREATE PROCEDURE SILVER.REPLAY_FLEET_MSSQL_CUSTOMER_V2", replay_sql)
        self.assertNotIn("CREATE OR REPLACE PROCEDURE SILVER.REPLAY_", replay_sql)
        self.assertIn("CREATE PROCEDURE SILVER.VALIDATE_FLEET_MSSQL_CUSTOMER_V2", validate_sql)
        self.assertNotIn("CREATE OR REPLACE PROCEDURE SILVER.VALIDATE_", validate_sql)

        self.assertIn("CREATE TASK SILVER.FLEET_MSSQL_CUSTOMER_V2_TASK", task_sql)
        self.assertNotIn("CREATE OR REPLACE TASK", task_sql)
        self.assertNotIn("CREATE TASK IF NOT EXISTS", task_sql)
        self.assertNotIn("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V2_TASK RESUME;\n", task_sql.split("-- Triggered task activation", 1)[0])

    def test_procedure_scoped_temp_tables_keep_runtime_replace_semantics(self) -> None:
        apply_sql = render_apply_sql("scd2", self.v2, SCD2_CONTRACT)
        replay_sql = render_replay_sql("scd2", self.v2, SCD2_CONTRACT)
        self.assertIn("CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE", apply_sql)
        self.assertIn("CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE", replay_sql)

    def test_initial_publication_is_create_only_and_candidate_is_not_published(self) -> None:
        initial = render_publish_sql("scd2", self.v1, candidate=False)
        candidate = render_publish_sql("scd2", self.v2, candidate=True)

        self.assertIn("CREATE VIEW SILVER.FLEET_MSSQL_CUSTOMER_HISTORY", initial)
        self.assertIn("CREATE VIEW SILVER.FLEET_MSSQL_CUSTOMER_CURRENT", initial)
        self.assertNotIn("OR REPLACE", initial)
        self.assertNotIn("COPY GRANTS", initial)

        self.assertIn("Candidate v2 is intentionally not published", candidate)
        self.assertNotIn("CREATE VIEW SILVER.FLEET_MSSQL_CUSTOMER_HISTORY", candidate)
        self.assertNotIn("CREATE OR REPLACE VIEW", candidate)

    def test_release_replaces_only_stable_views_with_copy_grants(self) -> None:
        activate, rollback = render_release_sql("scd2", self.v1, self.v2)

        self.assertIn(
            "CREATE OR REPLACE VIEW SILVER.FLEET_MSSQL_CUSTOMER_HISTORY COPY GRANTS AS",
            activate,
        )
        self.assertIn(
            "CREATE OR REPLACE VIEW SILVER.FLEET_MSSQL_CUSTOMER_CURRENT COPY GRANTS AS",
            activate,
        )
        self.assertIn("FROM SILVER.FLEET_MSSQL_CUSTOMER_V2_HISTORY", activate)
        self.assertIn("COPY GRANTS", rollback)
        self.assertIn("FROM SILVER.FLEET_MSSQL_CUSTOMER_V1_HISTORY", rollback)

    def test_release_starts_candidate_before_publication_and_retires_old_task_last(self) -> None:
        activate, _ = render_release_sql("scd2", self.v1, self.v2)
        resume_new = activate.index("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V2_TASK RESUME")
        publish = activate.index("CREATE OR REPLACE VIEW SILVER.FLEET_MSSQL_CUSTOMER_HISTORY COPY GRANTS")
        control = activate.index("ACTIVE_VERSION = 'v2'")
        suspend_old = activate.index("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V1_TASK SUSPEND")

        self.assertLess(resume_new, publish)
        self.assertLess(publish, control)
        self.assertLess(control, suspend_old)
        self.assertEqual(suspend_old, activate.rfind("ALTER TASK"))

    def test_new_dataset_migration_does_not_reexecute_existing_task_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "control_plane").mkdir()
            (root / "silver_processing" / "source_a" / "dataset_a").mkdir(parents=True)
            (root / "silver_processing" / "source_b" / "dataset_b").mkdir(parents=True)

            control_path = "control_plane/001_objects.sql"
            task_a_path = "silver_processing/source_a/dataset_a/030_task.sql"
            task_b_path = "silver_processing/source_b/dataset_b/030_task.sql"
            (root / control_path).write_text("select 1;\n", encoding="utf-8")
            (root / task_a_path).write_text("CREATE TASK A AS SELECT 1;\n", encoding="utf-8")
            (root / task_b_path).write_text("CREATE TASK B AS SELECT 1;\n", encoding="utf-8")
            (root / "control_plane" / "deploy_manifest.txt").write_text(control_path + "\n", encoding="utf-8")
            (root / "silver_processing" / "deploy_manifest.txt").write_text(
                task_a_path + "\n" + task_b_path + "\n", encoding="utf-8"
            )

            migrations = load_migrations(root)
            by_path = {item.path: item for item in migrations}
            history = (
                HistoryRecord(
                    attempt_id="control",
                    scope="CONTROL",
                    path=control_path,
                    checksum_sha256=by_path[control_path].checksum_sha256,
                    manifest_position=1,
                    status="SUCCEEDED",
                ),
                HistoryRecord(
                    attempt_id="task-a",
                    scope="SILVER",
                    path=task_a_path,
                    checksum_sha256=by_path[task_a_path].checksum_sha256,
                    manifest_position=1,
                    status="SUCCEEDED",
                ),
            )
            plan = build_migration_plan(migrations, history)
            decisions = {item.migration.path: item.action for item in plan.decisions}

            self.assertTrue(plan.ready)
            self.assertEqual("SKIP", decisions[task_a_path])
            self.assertEqual("APPLY", decisions[task_b_path])


if __name__ == "__main__":
    unittest.main()
