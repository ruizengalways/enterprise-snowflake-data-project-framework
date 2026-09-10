from __future__ import annotations

import unittest
from pathlib import Path

from enterprise_snowflake_framework.control_plan import KNOWN_CONTROL_SQL
from enterprise_snowflake_framework.template_provenance import FRAMEWORK_VERSION


class DocumentationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.readme = (cls.root / "README.md").read_text(encoding="utf-8")
        cls.current = (cls.root / "docs" / "CURRENT_CONTEXT.md").read_text(encoding="utf-8")
        cls.handoff = (cls.root / "docs" / "NEXT_CHAT_HANDOFF.md").read_text(encoding="utf-8")
        cls.naming = (cls.root / "docs" / "architecture" / "NAMING_AND_LAYERS.md").read_text(
            encoding="utf-8"
        )

    def test_current_docs_track_framework_release_identity(self) -> None:
        self.assertIn(f"version    = {FRAMEWORK_VERSION}", self.current)
        self.assertIn(f"version    = {FRAMEWORK_VERSION}", self.handoff)

    def test_key_docs_track_every_released_control_migration(self) -> None:
        for path in KNOWN_CONTROL_SQL:
            filename = Path(path).name
            with self.subTest(filename=filename):
                self.assertIn(filename, self.readme)
                self.assertIn(filename, self.current)
                self.assertIn(filename, self.handoff)

    def test_root_cli_examples_include_upgrade_planning(self) -> None:
        self.assertIn("esf upgrade-plan --project-root .", self.readme)
        self.assertIn("docs/architecture/TEMPLATE_PROVENANCE.md", self.readme)

    def test_logical_and_physical_layer_vocabulary_are_explicitly_separated(self) -> None:
        for logical in ("Bronze", "Silver", "Gold / Marts", "Semantic", "Control"):
            self.assertIn(logical, self.naming)
        for physical in ("BRONZE", "SILVER", "GOLD_MARTS", "SEMANTIC", "CONTROL"):
            self.assertIn(physical, self.naming)
        self.assertIn("PLATFORM_CONTROL", self.naming)
        self.assertIn("what **not** to build", self.naming)


if __name__ == "__main__":
    unittest.main()
