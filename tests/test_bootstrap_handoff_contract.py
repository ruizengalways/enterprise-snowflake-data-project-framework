import unittest
from pathlib import Path

from enterprise_snowflake_framework.bootstrap_validation import validate_bootstrap_metadata


class BootstrapHandoffContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path("contracts/raw/vehicle_status.yml")
        self.contract = {
            "business_key": ["vehicle_id"],
            "change_semantics": {
                "mode": "cdc",
                "operation_column": "source_operation",
                "sequence_column": "source_sequence",
                "delete_semantics": "tombstone",
            },
            "capture": {
                "archetype": "full_change",
                "fidelity": "full_change",
                "checkpoint_kind": "source_position",
                "ordering_columns": ["source_sequence"],
                "idempotency_columns": ["vehicle_id", "source_sequence"],
                "bootstrap": {
                    "mode": "snapshot_then_incremental",
                    "snapshot_consistency": "at_handoff_position",
                    "incremental_start": "exclusive",
                    "reconciliation_required": True,
                },
            },
        }

    def test_valid_full_change_handoff_has_no_errors(self) -> None:
        self.assertEqual(validate_bootstrap_metadata(self.contract, self.path), [])

    def test_snapshot_archetype_cannot_claim_incremental_handoff(self) -> None:
        self.contract["capture"]["archetype"] = "snapshot"
        self.contract["capture"]["checkpoint_kind"] = "snapshot_id"
        errors = validate_bootstrap_metadata(self.contract, self.path)
        self.assertTrue(any("not valid for capture.archetype=snapshot" in error for error in errors))

    def test_handoff_requires_resumable_source_position(self) -> None:
        self.contract["capture"]["archetype"] = "cursor_or_file"
        self.contract["capture"]["checkpoint_kind"] = "file_identity"
        errors = validate_bootstrap_metadata(self.contract, self.path)
        self.assertTrue(any("resumable steady-state handoff checkpoint" in error for error in errors))

    def test_inclusive_boundary_requires_deterministic_deduplication_identity(self) -> None:
        self.contract["capture"]["bootstrap"]["incremental_start"] = "inclusive_with_deduplication"
        self.contract["capture"].pop("idempotency_columns")
        errors = validate_bootstrap_metadata(self.contract, self.path)
        self.assertTrue(any("requires capture.idempotency_columns" in error for error in errors))

    def test_snapshot_change_semantics_cannot_be_the_steady_state_contract(self) -> None:
        self.contract["change_semantics"]["mode"] = "snapshot"
        errors = validate_bootstrap_metadata(self.contract, self.path)
        self.assertTrue(any("must not remain snapshot" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
