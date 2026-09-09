from __future__ import annotations

import unittest
from pathlib import Path

from enterprise_snowflake_framework.scaffold import SUPPORTED_PATTERNS


class SilverFirstToolkitTests(unittest.TestCase):
    def test_packaged_contracts_and_templates_are_available(self) -> None:
        package_root = Path(
            __import__("enterprise_snowflake_framework.scaffold", fromlist=["x"]).__file__
        ).resolve().parent
        self.assertTrue((package_root / "schemas" / "source_manifest.schema.json").is_file())
        self.assertTrue((package_root / "schemas" / "silver_pipeline.schema.json").is_file())
        for pattern in sorted(SUPPORTED_PATTERNS):
            self.assertTrue((package_root / "templates" / pattern / "010_apply.sql").is_file())
        self.assertTrue((package_root / "templates" / "project" / "project.yml").is_file())

    def test_runtime_framework_abstractions_are_not_part_of_supported_patterns(self) -> None:
        self.assertEqual({"append", "full_refresh", "scd1", "scd2", "custom"}, SUPPORTED_PATTERNS)


if __name__ == "__main__":
    unittest.main()
