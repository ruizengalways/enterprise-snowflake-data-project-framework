from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.validation import validate_version_document


class TaskPolicySemanticValidationTests(unittest.TestCase):
    def _path(self, root: Path) -> Path:
        return root / "silver_processing" / "fleet_mssql" / "customer" / "version.yml"

    def _document(self, *, minimum_trigger_interval_seconds: int = 60) -> dict:
        return {
            "schema_version": 1,
            "version": {
                "dataset": "fleet_mssql.customer",
                "id": "v1",
                "initial_status": "active",
                "activation": "explicit",
                "execution_model": "stream_task",
                "task": {
                    "warehouse": "WH_TRANSPORT_TRANSFORM",
                    "minimum_trigger_interval_seconds": minimum_trigger_interval_seconds,
                },
            },
        }

    def _manifests(self, pattern: str) -> dict[str, dict]:
        return {
            "fleet_mssql": {
                "datasets": {
                    "customer": {
                        "pattern": pattern,
                        "raw_contract": "contracts/raw/fleet_mssql/customer.yml",
                    }
                }
            }
        }

    def test_manual_full_refresh_trigger_interval_fails_project_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            errors = validate_version_document(
                self._document(),
                self._path(root),
                root,
                self._manifests("full_refresh"),
            )

        self.assertEqual(1, len(errors))
        self.assertIn("only valid for stream-triggered", errors[0])

    def test_same_task_policy_is_valid_for_stream_triggered_scd2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            errors = validate_version_document(
                self._document(),
                self._path(root),
                root,
                self._manifests("scd2"),
            )

        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
