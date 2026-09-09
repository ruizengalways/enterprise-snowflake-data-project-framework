from __future__ import annotations

import json
import unittest
from pathlib import Path

from enterprise_snowflake_framework.dbt_vars import build_dbt_vars
from enterprise_snowflake_framework.metadata_validation import validate_project_tree


class CleanV2ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.project = cls.root / "examples" / "mixed-strategy-project"
        cls.schema_dir = cls.root / "project_schema"

    def test_mixed_strategy_project_validates(self) -> None:
        self.assertEqual([], validate_project_tree(self.project, self.schema_dir))

    def test_strategy_axes_are_orthogonal_and_legacy_names_are_absent(self) -> None:
        schema = json.loads((self.schema_dir / "dataset.schema.json").read_text(encoding="utf-8"))
        dataset = schema["properties"]["dataset"]["properties"]
        self.assertEqual(
            ["full_refresh", "append_only", "incremental_merge", "scd1", "scd2", "custom"],
            dataset["load"]["properties"]["strategy"]["enum"],
        )
        self.assertIn("materialization", dataset)
        self.assertIn("runtime", dataset)
        self.assertNotIn("load_strategy", dataset)
        self.assertNotIn("implementation", dataset)

    def test_dbt_vars_have_no_compatibility_aliases(self) -> None:
        values = build_dbt_vars(self.project, self.schema_dir)
        datasets = values["esf_datasets"]
        self.assertEqual(
            {"append_only", "custom", "full_refresh", "incremental_merge", "scd1", "scd2"},
            {d["load"]["strategy"] for d in datasets.values() if d.get("load")},
        )
        for dataset in datasets.values():
            self.assertNotIn("load_strategy", dataset)
            self.assertNotIn("implementation", dataset)
        self.assertEqual("dynamic_table", datasets["gold_aggregation"]["materialization"]["type"])
        self.assertEqual("snowflake_managed", datasets["gold_aggregation"]["runtime"]["mode"])


if __name__ == "__main__":
    unittest.main()
