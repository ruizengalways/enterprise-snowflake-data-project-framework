from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.cli import _build_parser
from enterprise_snowflake_framework.execution_model import (
    TaskExecution,
    load_version_execution,
    validate_task_execution,
)
from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.scaffold import scaffold_pipeline, scaffold_preview
from enterprise_snowflake_framework.source_management import add_source
from enterprise_snowflake_framework.validation import validate_project_tree


RAW_TEMPLATE = """schema_version: 2
contract:
  source_system: fleet_mssql
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


class TaskOperationalConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(self.root)
        add_source(self.root, "fleet_mssql")
        raw = self.root / "contracts" / "raw" / "fleet_mssql" / "customer.yml"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(RAW_TEMPLATE, encoding="utf-8")
        self._write_manifest("scd2")

    def _write_manifest(self, pattern: str) -> None:
        manifest = {
            "schema_version": 1,
            "source": {"id": "fleet_mssql", "owner": "transport"},
            "datasets": {
                "customer": {
                    "pattern": pattern,
                    "raw_contract": "contracts/raw/fleet_mssql/customer.yml",
                }
            },
        }
        (self.root / "config" / "sources" / "fleet_mssql.yml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )

    def test_task_policy_is_version_local_and_maps_to_create_task(self) -> None:
        result = scaffold_pipeline(
            project_root=self.root,
            source_id="fleet_mssql",
            pattern="scd2",
            dataset_id="customer",
            execution_model="stream_task",
            warehouse="wh_transport_heavy",
            task_minimum_trigger_interval_seconds=60,
            task_timeout_seconds=900,
            task_suspend_after_failures=3,
            task_error_integration="task_error_notifications",
        )

        version = yaml.safe_load((result.destination / "version.yml").read_text(encoding="utf-8"))
        task = version["version"]["task"]
        self.assertEqual("WH_TRANSPORT_HEAVY", task["warehouse"])
        self.assertEqual(60, task["minimum_trigger_interval_seconds"])
        self.assertEqual(900, task["timeout_seconds"])
        self.assertEqual(3, task["suspend_after_failures"])
        self.assertEqual("TASK_ERROR_NOTIFICATIONS", task["error_integration"])
        self.assertEqual(2, version["version"]["provenance"]["template_revision"])

        sql = (result.destination / "030_task.sql").read_text(encoding="utf-8")
        self.assertIn("WAREHOUSE = WH_TRANSPORT_HEAVY", sql)
        self.assertIn("USER_TASK_MINIMUM_TRIGGER_INTERVAL_IN_SECONDS = 60", sql)
        self.assertIn("USER_TASK_TIMEOUT_MS = 900000", sql)
        self.assertIn("SUSPEND_TASK_AFTER_NUM_FAILURES = 3", sql)
        self.assertIn("ERROR_INTEGRATION = TASK_ERROR_NOTIFICATIONS", sql)
        self.assertIn("WHEN SYSTEM$STREAM_HAS_DATA", sql)
        self.assertNotIn("TASK_AUTO_RETRY_ATTEMPTS", sql)
        self.assertNotIn("SCHEDULE =", sql)

        source_text = (self.root / "config" / "sources" / "fleet_mssql.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("minimum_trigger_interval", source_text)
        self.assertNotIn("error_integration", source_text)
        self.assertFalse(validate_project_tree(self.root))

    def test_unspecified_optional_task_properties_preserve_snowflake_defaults(self) -> None:
        preview = scaffold_preview(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
        )
        version = yaml.safe_load(preview.rendered["version.yml"])
        task = version["version"]["task"]
        self.assertEqual(["warehouse"], list(task))

        sql = preview.rendered["030_task.sql"]
        self.assertIn("WAREHOUSE = WH_TRANSPORT_TRANSFORM", sql)
        self.assertNotIn("USER_TASK_MINIMUM_TRIGGER_INTERVAL_IN_SECONDS", sql)
        self.assertNotIn("USER_TASK_TIMEOUT_MS", sql)
        self.assertNotIn("SUSPEND_TASK_AFTER_NUM_FAILURES", sql)
        self.assertNotIn("ERROR_INTEGRATION", sql)

    def test_trigger_interval_bounds_and_readiness_scope_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 10 and 604800"):
            validate_task_execution(
                "scd2", TaskExecution("WH_TRANSPORT_TRANSFORM", minimum_trigger_interval_seconds=9)
            )
        with self.assertRaisesRegex(ValueError, "between 10 and 604800"):
            validate_task_execution(
                "scd2",
                TaskExecution("WH_TRANSPORT_TRANSFORM", minimum_trigger_interval_seconds=604801),
            )
        with self.assertRaisesRegex(ValueError, "only valid for stream-triggered"):
            validate_task_execution(
                "full_refresh",
                TaskExecution("WH_TRANSPORT_TRANSFORM", minimum_trigger_interval_seconds=60),
            )

    def test_timeout_and_failure_bounds_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 0 and 604800"):
            validate_task_execution(
                "scd2", TaskExecution("WH_TRANSPORT_TRANSFORM", timeout_seconds=-1)
            )
        with self.assertRaisesRegex(ValueError, "between 0 and 604800"):
            validate_task_execution(
                "scd2", TaskExecution("WH_TRANSPORT_TRANSFORM", timeout_seconds=604801)
            )
        with self.assertRaisesRegex(ValueError, "zero or greater"):
            validate_task_execution(
                "scd2", TaskExecution("WH_TRANSPORT_TRANSFORM", suspend_after_failures=-1)
            )

    def test_task_options_are_rejected_for_dynamic_table(self) -> None:
        self._write_manifest("scd1")
        with self.assertRaisesRegex(ValueError, "require execution_model=stream_task"):
            scaffold_preview(
                project_root=self.root,
                source_id="fleet_mssql",
                dataset_id="customer",
                execution_model="dynamic_table",
                task_timeout_seconds=30,
            )

    def test_legacy_stream_task_version_without_task_block_still_loads(self) -> None:
        result = scaffold_pipeline(
            project_root=self.root,
            source_id="fleet_mssql",
            pattern="scd2",
            dataset_id="customer",
        )
        version_path = result.destination / "version.yml"
        document = yaml.safe_load(version_path.read_text(encoding="utf-8"))
        del document["version"]["task"]
        version_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

        execution = load_version_execution(
            self.root, "fleet_mssql", "customer", "v1", pattern="scd2"
        )
        self.assertEqual("stream_task", execution.execution_model)
        self.assertIsNone(execution.task)
        self.assertFalse(validate_project_tree(self.root))

    def test_cli_exposes_only_the_narrow_task_policy_surface(self) -> None:
        args = _build_parser().parse_args(
            [
                "scaffold-version",
                "customer",
                "v2",
                "--source",
                "fleet_mssql",
                "--warehouse",
                "wh_transport_heavy",
                "--task-minimum-trigger-interval-seconds",
                "60",
                "--task-timeout-seconds",
                "900",
                "--task-suspend-after-failures",
                "3",
                "--task-error-integration",
                "task_errors",
            ]
        )
        self.assertEqual(60, args.task_minimum_trigger_interval_seconds)
        self.assertEqual(900, args.task_timeout_seconds)
        self.assertEqual(3, args.task_suspend_after_failures)
        self.assertEqual("task_errors", args.task_error_integration)
        self.assertFalse(hasattr(args, "task_auto_retry_attempts"))
        self.assertFalse(hasattr(args, "schedule"))


if __name__ == "__main__":
    unittest.main()
