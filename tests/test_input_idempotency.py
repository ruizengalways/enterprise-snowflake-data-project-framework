from __future__ import annotations

import unittest

from enterprise_snowflake_framework.pipeline_model import build_names
from enterprise_snowflake_framework.pipeline_sql import render_apply_sql, render_replay_sql


APPEND_CONTRACT = {
    "business_key": ["vehicle_id"],
    "source_timestamp": "event_timestamp",
    "columns": [
        {"name": "vehicle_id", "type": "VARCHAR", "nullable": False},
        {"name": "event_timestamp", "type": "TIMESTAMP_NTZ", "nullable": False},
        {"name": "latitude", "type": "FLOAT", "nullable": False},
        {"name": "ingested_at", "type": "TIMESTAMP_NTZ", "nullable": False},
    ],
    "change_semantics": {"mode": "append", "delete_semantics": "none"},
    "capture_fidelity": "full_event",
    "ordering_columns": ["event_timestamp"],
    "idempotency_key": ["vehicle_id", "event_timestamp"],
}

SCD2_CONTRACT = {
    "business_key": ["vehicle_id"],
    "source_timestamp": "source_updated_at",
    "columns": [
        {"name": "vehicle_id", "type": "VARCHAR", "nullable": False},
        {"name": "status", "type": "VARCHAR", "nullable": True},
        {"name": "source_updated_at", "type": "TIMESTAMP_NTZ", "nullable": False},
        {"name": "source_sequence", "type": "NUMBER", "nullable": False},
        {"name": "source_operation", "type": "VARCHAR", "nullable": False},
        {"name": "ingested_at", "type": "TIMESTAMP_NTZ", "nullable": False},
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
    "idempotency_key": ["vehicle_id", "source_sequence"],
}


class InputIdempotencyTests(unittest.TestCase):
    def _names(self, pattern: str):
        return build_names(
            source_id="transport_source",
            dataset_id="vehicle",
            pattern=pattern,
            entity="vehicle",
            version="v1",
        )

    def test_append_apply_dedupes_exact_batch_duplicates_and_fails_conflicts(self) -> None:
        sql = render_apply_sql("append", self._names("append"), APPEND_CONTRACT)
        self.assertIn("E_IDEMPOTENCY_CONFLICT EXCEPTION", sql)
        self.assertIn("V_IDEMPOTENCY_CONFLICTS", sql)
        self.assertIn("HAVING COUNT(DISTINCT TO_VARCHAR(HASH(", sql)
        self.assertIn("GROUP BY I.VEHICLE_ID, I.EVENT_TIMESTAMP", sql)
        self.assertIn("PARTITION BY D.VEHICLE_ID, D.EVENT_TIMESTAMP", sql)
        self.assertIn("FROM ESF_NEW_EVENTS D", sql)
        self.assertIn("RAISE E_IDEMPOTENCY_CONFLICT", sql)
        self.assertIn("T.VEHICLE_ID = N.VEHICLE_ID", sql)

    def test_append_replay_uses_same_batch_identity_guard(self) -> None:
        sql = render_replay_sql("append", self._names("append"), APPEND_CONTRACT)
        self.assertIn("ESF_REPLAY_INPUT", sql)
        self.assertIn("E_IDEMPOTENCY_CONFLICT EXCEPTION", sql)
        self.assertIn("GROUP BY I.VEHICLE_ID, I.EVENT_TIMESTAMP", sql)
        self.assertIn("PARTITION BY D.VEHICLE_ID, D.EVENT_TIMESTAMP", sql)
        self.assertIn("FROM ESF_REPLAY_INPUT D", sql)
        self.assertIn("T.VEHICLE_ID = N.VEHICLE_ID", sql)

    def test_scd2_apply_identity_includes_stream_action(self) -> None:
        sql = render_apply_sql("scd2", self._names("scd2"), SCD2_CONTRACT)
        self.assertIn(
            "GROUP BY I.VEHICLE_ID, I.SOURCE_SEQUENCE, I.ESF_STREAM_ACTION", sql
        )
        self.assertIn(
            "PARTITION BY D.VEHICLE_ID, D.SOURCE_SEQUENCE, D.ESF_STREAM_ACTION", sql
        )
        self.assertIn("I.ESF_STREAM_ISUPDATE", sql)
        self.assertIn("E.ESF_STREAM_ACTION = N.ESF_STREAM_ACTION", sql)
        self.assertIn("RAISE E_IDEMPOTENCY_CONFLICT", sql)

    def test_scd2_replay_stages_action_before_conflict_detection(self) -> None:
        sql = render_replay_sql("scd2", self._names("scd2"), SCD2_CONTRACT)
        self.assertIn("ESF_REPLAY_INPUT", sql)
        self.assertIn("ESF_STREAM_ACTION VARCHAR NOT NULL", sql)
        self.assertIn(
            "GROUP BY I.VEHICLE_ID, I.SOURCE_SEQUENCE, I.ESF_STREAM_ACTION", sql
        )
        self.assertIn(
            "PARTITION BY D.VEHICLE_ID, D.SOURCE_SEQUENCE, D.ESF_STREAM_ACTION", sql
        )
        self.assertIn("E.ESF_STREAM_ACTION = N.ESF_STREAM_ACTION", sql)
        self.assertIn("RAISE E_IDEMPOTENCY_CONFLICT", sql)

    def test_unrelated_patterns_do_not_gain_the_new_batch_identity_guard(self) -> None:
        full_refresh = {
            **APPEND_CONTRACT,
            "change_semantics": {"mode": "snapshot", "delete_semantics": "none"},
        }
        sql = render_apply_sql("full_refresh", self._names("full_refresh"), full_refresh)
        self.assertNotIn("E_IDEMPOTENCY_CONFLICT", sql)


if __name__ == "__main__":
    unittest.main()
