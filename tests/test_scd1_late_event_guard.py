from __future__ import annotations

import unittest

from enterprise_snowflake_framework.pipeline_sql import build_names, render_apply_sql


class Scd1LateEventGuardTests(unittest.TestCase):
    def test_scd1_matched_change_requires_strictly_newer_ordering_tuple(self) -> None:
        contract = {
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
        names = build_names(
            source_id="fleet_mssql",
            dataset_id="customer",
            pattern="scd1",
            entity="customer",
            version="v2",
        )
        sql = render_apply_sql("scd1", names, contract)
        newer = (
            "((N.SOURCE_UPDATED_AT > T.SOURCE_UPDATED_AT) OR "
            "(N.SOURCE_UPDATED_AT = T.SOURCE_UPDATED_AT AND N.SOURCE_SEQUENCE > T.SOURCE_SEQUENCE))"
        )
        self.assertIn(f"WHEN MATCHED AND {newer} AND", sql)
        self.assertIn(f"WHEN MATCHED AND {newer} THEN UPDATE SET", sql)
        self.assertIn("late or out-of-order event must not regress", sql)
        self.assertNotIn("WHEN MATCHED THEN UPDATE SET", sql)

    def test_scd1_without_ordering_evidence_does_not_invent_recency(self) -> None:
        contract = {
            "entity": "customer",
            "business_key": ["id"],
            "columns": [
                {"name": "id", "type": "VARCHAR", "nullable": False},
                {"name": "value", "type": "VARCHAR", "nullable": True},
            ],
            "change_semantics": {"mode": "append", "delete_semantics": "none"},
            "idempotency_key": ["id"],
        }
        names = build_names(
            source_id="source_a",
            dataset_id="customer",
            pattern="scd1",
            entity="customer",
            version="v1",
        )
        sql = render_apply_sql("scd1", names, contract)
        self.assertIn("WHEN MATCHED AND TRUE THEN UPDATE SET", sql)


if __name__ == "__main__":
    unittest.main()
