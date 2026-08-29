import json
import unittest

from enterprise_snowflake_framework.query_tags import build_query_tag


class QueryTagTests(unittest.TestCase):
    def test_tag_is_compact_deterministic_json(self) -> None:
        tag = build_query_tag(
            {
                "workload": "transform",
                "project": "health",
                "environment": "dev",
                "dataset": "patient",
                "run_id": "run-123",
            }
        )
        self.assertEqual(
            tag,
            '{"dataset":"patient","environment":"dev","project":"health","run_id":"run-123","workload":"transform"}',
        )
        self.assertEqual(json.loads(tag)["project"], "health")

    def test_missing_required_key_fails(self) -> None:
        with self.assertRaises(ValueError):
            build_query_tag({"project": "health", "environment": "dev"})

    def test_unknown_key_fails(self) -> None:
        with self.assertRaises(ValueError):
            build_query_tag(
                {
                    "project": "health",
                    "environment": "dev",
                    "workload": "transform",
                    "employee_email": "not-allowed@example.com",
                }
            )

    def test_oversized_tag_fails_before_snowflake_truncation(self) -> None:
        with self.assertRaises(ValueError):
            build_query_tag(
                {
                    "project": "health",
                    "environment": "dev",
                    "workload": "transform",
                    "pipeline": "x" * 2100,
                }
            )


if __name__ == "__main__":
    unittest.main()
