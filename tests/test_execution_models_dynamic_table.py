from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.execution_model import validate_execution_model
from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.lifecycle import generate_lifecycle_scripts
from enterprise_snowflake_framework.scaffold import scaffold_pipeline
from enterprise_snowflake_framework.source_management import add_source
from enterprise_snowflake_framework.validation import validate_project_tree
from enterprise_snowflake_framework.versioning import generate_release_scripts, scaffold_version


SCD1_CONTRACT = {
    "source_system": "fleet_mssql",
    "entity": "customer",
    "grain": "one row per source change",
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
    "capture_fidelity": "full_change",
    "ordering_columns": ["source_updated_at", "source_sequence"],
    "idempotency_key": ["id", "source_sequence"],
    "breaking_change_policy": "versioned_contract",
}


class ExecutionModelDynamicTableTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        project = root / "enterprise-snowflake-transport-analytics"
        initialize_project(project)
        add_source(project, "fleet_mssql")
        raw = project / "contracts" / "raw" / "fleet_mssql" / "customer.yml"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(
            yaml.safe_dump({"schema_version": 2, "contract": SCD1_CONTRACT}, sort_keys=False),
            encoding="utf-8",
        )
        manifest = {
            "schema_version": 1,
            "source": {"id": "fleet_mssql", "owner": "transport-data"},
            "datasets": {
                "customer": {
                    "pattern": "scd1",
                    "raw_contract": "contracts/raw/fleet_mssql/customer.yml",
                }
            },
        }
        (project / "config" / "sources" / "fleet_mssql.yml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )
        scaffold_pipeline(
            project_root=project,
            source_id="fleet_mssql",
            pattern="scd1",
            dataset_id="customer",
        )
        return project

    def test_candidate_dynamic_table_has_no_fake_stream_task_or_apply_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            result = scaffold_version(
                project_root=project,
                source_id="fleet_mssql",
                dataset_id="customer",
                version="v2",
                execution_model="dynamic_table",
                target_lag="3 minutes",
                warehouse="WH_TRANSPORT_TRANSFORM",
                refresh_mode="incremental",
            )
            names = {path.name for path in result.destination.iterdir() if path.is_file()}
            self.assertIn("001_dynamic_table.sql", names)
            self.assertIn("020_validate.sql", names)
            self.assertIn("040_register.sql", names)
            self.assertNotIn("001_objects.sql", names)
            self.assertNotIn("010_apply.sql", names)
            self.assertNotIn("015_replay.sql", names)
            self.assertNotIn("030_task.sql", names)

            sql = (result.destination / "001_dynamic_table.sql").read_text(encoding="utf-8")
            self.assertIn("CREATE DYNAMIC TABLE SILVER.FLEET_MSSQL_CUSTOMER_V2", sql)
            self.assertIn("TARGET_LAG = '3 minutes'", sql)
            self.assertIn("REFRESH_MODE = INCREMENTAL", sql)
            self.assertIn("ROW_NUMBER() OVER", sql)
            self.assertNotIn("CREATE TASK", sql)
            self.assertNotIn("CREATE STREAM", sql)
            version = yaml.safe_load((result.destination / "version.yml").read_text(encoding="utf-8"))
            self.assertEqual("dynamic_table", version["version"]["execution_model"])
            self.assertEqual("3 minutes", version["version"]["dynamic_table"]["target_lag"])

            register = (result.destination / "040_register.sql").read_text(encoding="utf-8")
            self.assertIn("V.EXECUTION_MODEL = 'dynamic_table'", register)
            self.assertIn("V.PRIMARY_RUNTIME_OBJECT = 'SILVER.FLEET_MSSQL_CUSTOMER_V2'", register)
            self.assertIn("V.TASK_OBJECT = NULL", register)
            self.assertIn("V.STREAM_OBJECT = NULL", register)
            self.assertIn("V.APPLY_OBJECT = NULL", register)

    def test_pattern_stays_logical_and_execution_model_stays_version_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            scaffold_version(
                project_root=project,
                source_id="fleet_mssql",
                dataset_id="customer",
                version="v2",
                execution_model="dynamic_table",
            )
            source = (project / "config" / "sources" / "fleet_mssql.yml").read_text(encoding="utf-8")
            pipeline = (project / "silver_processing" / "fleet_mssql" / "customer" / "pipeline.yml").read_text(encoding="utf-8")
            v1 = yaml.safe_load((project / "silver_processing" / "fleet_mssql" / "customer" / "version.yml").read_text(encoding="utf-8"))
            v2 = yaml.safe_load((project / "silver_processing" / "fleet_mssql" / "customer" / "versions" / "v2" / "version.yml").read_text(encoding="utf-8"))
            self.assertNotIn("execution_model", source)
            self.assertNotIn("execution_model", pipeline)
            self.assertEqual("scd1", yaml.safe_load(source)["datasets"]["customer"]["pattern"])
            self.assertEqual("stream_task", v1["version"]["execution_model"])
            self.assertEqual("dynamic_table", v2["version"]["execution_model"])

    def test_unsupported_semantic_execution_combinations_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not support execution_model=dynamic_table"):
            validate_execution_model("scd2", "dynamic_table")
        with self.assertRaisesRegex(ValueError, "does not support execution_model=dynamic_table"):
            validate_execution_model("append", "dynamic_table")
        with self.assertRaisesRegex(ValueError, "does not support execution_model=batch_sql"):
            validate_execution_model("scd1", "batch_sql")
        validate_execution_model("full_refresh", "batch_sql")
        validate_execution_model("full_refresh", "dynamic_table")

    def test_release_and_lifecycle_are_execution_model_aware(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            scaffold_version(
                project_root=project,
                source_id="fleet_mssql",
                dataset_id="customer",
                version="v2",
                execution_model="dynamic_table",
            )
            release = generate_release_scripts(
                project_root=project,
                source_id="fleet_mssql",
                dataset_id="customer",
                from_version="v1",
                to_version="v2",
            )
            activate = (release.destination / "activate.sql").read_text(encoding="utf-8")
            self.assertIn("candidate Dynamic Table must already be refreshed/caught up before preflight", activate)
            self.assertNotIn("ALTER DYNAMIC TABLE SILVER.FLEET_MSSQL_CUSTOMER_V2 REFRESH", activate)
            self.assertIn("CREATE OR REPLACE VIEW SILVER.FLEET_MSSQL_CUSTOMER COPY GRANTS", activate)
            self.assertIn("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V1_TASK SUSPEND", activate)
            self.assertIn("FROM CONTROL.RELEASE_READINESS_V", activate)
            self.assertLess(activate.index("CREATE OR REPLACE VIEW"), activate.index("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V1_TASK SUSPEND"))

            lifecycle = generate_lifecycle_scripts(
                project_root=project,
                source_id="fleet_mssql",
                dataset_id="customer",
                action="pause",
                operation_id="pause-v2",
                version="v2",
            )
            operation = (lifecycle.destination / "operation.sql").read_text(encoding="utf-8")
            self.assertIn("ALTER DYNAMIC TABLE SILVER.FLEET_MSSQL_CUSTOMER_V2 SUSPEND", operation)
            self.assertNotIn("ALTER TASK SILVER.FLEET_MSSQL_CUSTOMER_V2_TASK", operation)

    def test_legacy_version_yaml_without_execution_model_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            version_path = project / "silver_processing" / "fleet_mssql" / "customer" / "version.yml"
            document = yaml.safe_load(version_path.read_text(encoding="utf-8"))
            document["version"].pop("execution_model", None)
            document["version"].pop("task", None)
            version_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            self.assertEqual([], validate_project_tree(project))

    def test_control_migrations_add_version_metadata_and_native_refresh_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "enterprise-snowflake-transport-analytics"
            initialize_project(project)
            manifest = (project / "control_plane" / "deploy_manifest.txt").read_text(encoding="utf-8")
            self.assertIn("control_plane/sql/090_dataset_execution_model.sql", manifest)
            self.assertIn("control_plane/sql/100_dynamic_table_observability.sql", manifest)
            migration90 = (project / "control_plane" / "sql" / "090_dataset_execution_model.sql").read_text(encoding="utf-8")
            migration100 = (project / "control_plane" / "sql" / "100_dynamic_table_observability.sql").read_text(encoding="utf-8")
            self.assertIn("ADD COLUMN EXECUTION_MODEL", migration90)
            self.assertIn("ADD COLUMN PRIMARY_RUNTIME_OBJECT", migration90)
            self.assertIn("INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY", migration100)
            self.assertIn("ACTIVE_EXECUTION_MODEL", migration100)
            self.assertNotIn("INSERT INTO CONTROL.PIPELINE_RUN", migration100)


if __name__ == "__main__":
    unittest.main()
