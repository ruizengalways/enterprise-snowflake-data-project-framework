from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.cli import _build_parser
from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.raw_contract_authoring import (
    create_raw_contract_draft,
    finalize_raw_contract,
    raw_contract_draft_path,
    raw_contract_path,
)
from enterprise_snowflake_framework.source_management import add_source
from enterprise_snowflake_framework.validation import validate_project_tree


VALID_RAW = """schema_version: 2
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


class RawContractAuthoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(self.root)
        add_source(self.root, "fleet_mssql")

    def test_draft_is_outside_raw_and_ignored_by_project_validation(self) -> None:
        result = create_raw_contract_draft(self.root, "fleet_mssql", "customer")

        self.assertTrue(result.created)
        self.assertEqual(
            self.root / "contracts" / "drafts" / "fleet_mssql" / "customer.yml",
            result.destination,
        )
        self.assertFalse(raw_contract_path(self.root, "fleet_mssql", "customer").exists())
        text = result.destination.read_text(encoding="utf-8")
        self.assertIn("RAW CONTRACT DRAFT ONLY", text)
        self.assertIn("TODO_BUSINESS_KEY", text)
        self.assertIn("does not infer business keys", text)
        self.assertEqual([], validate_project_tree(self.root))

    def test_existing_draft_is_never_overwritten(self) -> None:
        first = create_raw_contract_draft(self.root, "fleet_mssql", "customer")
        first.destination.write_text("# DOMAIN WORK IN PROGRESS\n", encoding="utf-8")
        before = first.destination.read_bytes()

        repeated = create_raw_contract_draft(self.root, "fleet_mssql", "customer")

        self.assertFalse(repeated.created)
        self.assertEqual("draft already exists", repeated.reason)
        self.assertEqual(before, first.destination.read_bytes())

    def test_finalize_refuses_unresolved_todo_and_keeps_draft(self) -> None:
        draft = create_raw_contract_draft(self.root, "fleet_mssql", "customer").destination

        with self.assertRaisesRegex(ValueError, "unresolved TODO"):
            finalize_raw_contract(self.root, "fleet_mssql", "customer")

        self.assertTrue(draft.is_file())
        self.assertFalse(raw_contract_path(self.root, "fleet_mssql", "customer").exists())

    def test_finalize_valid_contract_promotes_exact_reviewed_bytes(self) -> None:
        draft = create_raw_contract_draft(self.root, "fleet_mssql", "customer").destination
        reviewed = "# engineer reviewed\n" + VALID_RAW
        draft.write_text(reviewed, encoding="utf-8")

        result = finalize_raw_contract(self.root, "fleet_mssql", "customer")

        self.assertTrue(result.created)
        self.assertFalse(draft.exists())
        self.assertEqual(raw_contract_path(self.root, "fleet_mssql", "customer"), result.destination)
        self.assertEqual(reviewed.encode(), result.destination.read_bytes())
        self.assertEqual([], validate_project_tree(self.root))

    def test_finalize_rejects_source_mismatch_without_promoting(self) -> None:
        draft = create_raw_contract_draft(self.root, "fleet_mssql", "customer").destination
        draft.write_text(VALID_RAW.replace("source_system: fleet_mssql", "source_system: gtfs_api"), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "source_system must match"):
            finalize_raw_contract(self.root, "fleet_mssql", "customer")

        self.assertTrue(draft.exists())
        self.assertFalse(raw_contract_path(self.root, "fleet_mssql", "customer").exists())

    def test_existing_formal_contract_is_never_overwritten(self) -> None:
        final = raw_contract_path(self.root, "fleet_mssql", "customer")
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_text("# DOMAIN OWNED FORMAL CONTRACT\n", encoding="utf-8")
        before = final.read_bytes()

        draft_result = create_raw_contract_draft(self.root, "fleet_mssql", "customer")
        finalize_result = finalize_raw_contract(self.root, "fleet_mssql", "customer")

        self.assertFalse(draft_result.created)
        self.assertFalse(finalize_result.created)
        self.assertEqual(before, final.read_bytes())

    def test_invalid_ids_and_missing_source_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            create_raw_contract_draft(self.root, "fleet_mssql", "Customer")
        with self.assertRaises(ValueError):
            create_raw_contract_draft(self.root, "../fleet", "customer")
        with self.assertRaises(FileNotFoundError):
            create_raw_contract_draft(self.root, "unknown_source", "customer")

    def test_cli_exposes_draft_and_finalize_without_force(self) -> None:
        parser = _build_parser()
        draft = parser.parse_args(
            ["raw-contract-draft", "customer", "--source", "fleet_mssql"]
        )
        finalize = parser.parse_args(
            ["raw-contract-finalize", "customer", "--source", "fleet_mssql"]
        )
        self.assertEqual("raw-contract-draft", draft.command)
        self.assertEqual("raw-contract-finalize", finalize.command)

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "raw-contract-draft",
                    "customer",
                    "--source",
                    "fleet_mssql",
                    "--force",
                ]
            )


if __name__ == "__main__":
    unittest.main()
