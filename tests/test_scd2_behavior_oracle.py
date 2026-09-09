import json
import unittest
from collections import defaultdict
from pathlib import Path
from typing import Any


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "scd2" / "event_history.json"


def build_expected_scd2_history(
    events: list[dict[str, Any]],
    *,
    business_key: list[str],
    effective_at_column: str,
    order_columns: list[str],
    tracked_columns: list[str],
    operation_column: str,
    delete_values: list[str],
) -> list[dict[str, Any]]:
    """Small test-only oracle mirroring the framework event-history semantics.

    This intentionally does not generate SQL and is not production pipeline code.
    It gives offline tests an independent semantic oracle for ordering, replay,
    tombstones, reinserts, and late-arriving events.
    """
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[tuple(event[column] for column in business_key)].append(event)

    history: list[dict[str, Any]] = []
    for key_value in sorted(grouped):
        ordered = sorted(
            grouped[key_value],
            key=lambda event: tuple(event[column] for column in order_columns),
        )

        state_changes: list[dict[str, Any]] = []
        previous_signature: tuple[Any, ...] | None = None
        previous_was_delete = False

        for event_ordinal, event in enumerate(ordered, start=1):
            signature = tuple(event.get(column) for column in tracked_columns)
            is_delete = event.get(operation_column) in delete_values
            is_state_change = (
                event_ordinal == 1
                or is_delete
                or previous_was_delete
                or signature != previous_signature
            )
            if is_state_change:
                state_changes.append({"event": event, "is_delete": is_delete})

            previous_signature = signature
            previous_was_delete = is_delete

        for version_ordinal, change in enumerate(state_changes, start=1):
            event = change["event"]
            next_effective_at = (
                state_changes[version_ordinal]["event"][effective_at_column]
                if version_ordinal < len(state_changes)
                else None
            )
            if change["is_delete"]:
                continue

            row = {column: event[column] for column in business_key}
            row.update({column: event.get(column) for column in tracked_columns})
            row.update(
                {
                    "valid_from": event[effective_at_column],
                    "valid_to": next_effective_at,
                    "is_current": next_effective_at is None,
                    "version_ordinal": version_ordinal,
                }
            )
            history.append(row)

    return history


class Scd2BehaviorOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def build(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return build_expected_scd2_history(
            events,
            business_key=self.fixture["business_key"],
            effective_at_column=self.fixture["effective_at_column"],
            order_columns=self.fixture["order_columns"],
            tracked_columns=self.fixture["tracked_columns"],
            operation_column=self.fixture["operation_column"],
            delete_values=self.fixture["delete_values"],
        )

    def test_fixture_covers_replay_update_delete_reinsert_and_late_arrival(self) -> None:
        self.assertEqual(self.build(self.fixture["events"]), self.fixture["expected_history"])

    def test_arrival_order_does_not_change_effective_history(self) -> None:
        reordered = list(reversed(self.fixture["events"]))
        self.assertEqual(self.build(reordered), self.fixture["expected_history"])

    def test_unchanged_replay_does_not_create_a_new_version(self) -> None:
        entity_b = [row for row in self.build(self.fixture["events"]) if row["entity_id"] == "B"]
        self.assertEqual([row["status"] for row in entity_b], ["bravo-v1", "bravo-v2"])
        self.assertEqual([row["version_ordinal"] for row in entity_b], [1, 2])

    def test_delete_boundary_closes_history_and_reinsert_reopens_it(self) -> None:
        entity_a = [row for row in self.build(self.fixture["events"]) if row["entity_id"] == "A"]
        self.assertEqual(entity_a[-2]["valid_to"], 40)
        self.assertEqual(entity_a[-1]["valid_from"], 50)
        self.assertTrue(entity_a[-1]["is_current"])
        self.assertEqual(entity_a[-1]["version_ordinal"], 5)


if __name__ == "__main__":
    unittest.main()
