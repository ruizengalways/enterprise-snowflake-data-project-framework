import unittest
from pathlib import Path

from enterprise_snowflake_framework.scd2_validation import validate_scd2_metadata


class Scd2MetadataContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path("config/datasets/vehicle_status.yml")
        self.contract = {
            "business_key": ["vehicle_id"],
            "columns": [
                {"name": "vehicle_id"},
                {"name": "status"},
                {"name": "depot_id"},
                {"name": "source_updated_at"},
                {"name": "source_sequence"},
                {"name": "source_event_id"},
                {"name": "source_operation"},
            ],
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
            },
        }
        self.dataset = {
            "load_strategy": "scd2_merge",
            "business_key": ["vehicle_id"],
            "scd2": {
                "effective_at_column": "source_updated_at",
                "order_columns": ["source_updated_at", "source_sequence"],
                "tracked_columns": ["status", "depot_id"],
                "operation_column": "source_operation",
                "delete_values": ["D"],
                "late_arriving_policy": "rebuild_affected_keys",
            },
        }

    def test_valid_contract_has_no_errors(self) -> None:
        self.assertEqual(validate_scd2_metadata(self.dataset, self.contract, self.path), [])

    def test_effective_timestamp_must_participate_in_ordering(self) -> None:
        self.dataset["scd2"]["order_columns"] = ["source_sequence"]
        errors = validate_scd2_metadata(self.dataset, self.contract, self.path)
        self.assertTrue(any("effective_at_column" in error for error in errors))

    def test_capture_ordering_must_be_preserved(self) -> None:
        self.dataset["scd2"]["order_columns"] = ["source_updated_at"]
        errors = validate_scd2_metadata(self.dataset, self.contract, self.path)
        self.assertTrue(any("raw capture ordering columns" in error for error in errors))

    def test_non_key_idempotency_columns_must_participate_in_ordering(self) -> None:
        self.contract["capture"]["idempotency_columns"] = [
            "vehicle_id",
            "source_sequence",
            "source_event_id",
        ]
        errors = validate_scd2_metadata(self.dataset, self.contract, self.path)
        self.assertTrue(any("non-key raw idempotency columns" in error for error in errors))

    def test_business_key_must_match_raw_contract(self) -> None:
        self.dataset["business_key"] = ["other_id"]
        errors = validate_scd2_metadata(self.dataset, self.contract, self.path)
        self.assertTrue(any("must exactly match raw contract business_key" in error for error in errors))

    def test_business_key_cannot_be_a_tracked_attribute(self) -> None:
        self.dataset["scd2"]["tracked_columns"] = ["vehicle_id", "status"]
        errors = validate_scd2_metadata(self.dataset, self.contract, self.path)
        self.assertTrue(any("must describe attributes" in error for error in errors))

    def test_tombstone_operation_column_must_match_raw_contract(self) -> None:
        self.dataset["scd2"]["operation_column"] = "different_operation"
        errors = validate_scd2_metadata(self.dataset, self.contract, self.path)
        self.assertTrue(any("tombstone SCD2" in error for error in errors))

    def test_scd2_block_is_rejected_for_non_scd2_strategy(self) -> None:
        self.dataset["load_strategy"] = "append_only"
        errors = validate_scd2_metadata(self.dataset, self.contract, self.path)
        self.assertEqual(len(errors), 1)
        self.assertIn("valid only for an SCD2", errors[0])


if __name__ == "__main__":
    unittest.main()
