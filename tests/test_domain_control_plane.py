from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.init_project import initialize_project


class DomainControlPlaneInitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"

    def test_init_creates_domain_local_control_plane_foundation(self) -> None:
        initialize_project(self.root)

        objects = self.root / "control_plane" / "sql" / "001_objects.sql"
        views = self.root / "control_plane" / "sql" / "010_observability_views.sql"
        refresh = self.root / "control_plane" / "sql" / "020_refresh_health.sql"

        self.assertTrue((self.root / "control_plane" / "README.md").is_file())
        self.assertTrue(objects.is_file())
        self.assertTrue(views.is_file())
        self.assertTrue(refresh.is_file())

        object_sql = objects.read_text(encoding="utf-8")
        self.assertIn("CREATE SCHEMA IF NOT EXISTS CONTROL", object_sql)
        self.assertIn("CONTROL.DATASET", object_sql)
        self.assertIn("CONTROL.DATASET_VERSION", object_sql)
        self.assertIn("CONTROL.SLA_POLICY", object_sql)
        self.assertIn("CONTROL.INGESTION_RUN", object_sql)
        self.assertIn("CONTROL.PIPELINE_RUN", object_sql)
        self.assertIn("CONTROL.DBT_RUN", object_sql)
        self.assertIn("CONTROL.DATASET_HEALTH", object_sql)
        self.assertIn("CONTROL.INCIDENT", object_sql)
        self.assertIn("CONTROL.REPAIR_RUN", object_sql)
        self.assertIn("CONTROL.VERSION_VALIDATION", object_sql)
        self.assertNotIn("PLATFORM_CONTROL", object_sql)

        view_sql = views.read_text(encoding="utf-8")
        self.assertIn("CONTROL.DATASET_HEALTH_V", view_sql)
        self.assertIn("CONTROL.DATASET_OBSERVABILITY_V", view_sql)

        refresh_sql = refresh.read_text(encoding="utf-8")
        self.assertIn("CONTROL.REFRESH_DATASET_HEALTH", refresh_sql)
        self.assertNotIn("APPLY_GENERIC_SCD", refresh_sql)

    def test_repeated_init_never_overwrites_domain_control_plane_sql(self) -> None:
        initialize_project(self.root)
        objects = self.root / "control_plane" / "sql" / "001_objects.sql"
        custom = "-- DOMAIN OWNED CONTROL PLANE\nselect 1;\n"
        objects.write_text(custom, encoding="utf-8")

        result = initialize_project(self.root)

        self.assertEqual(custom, objects.read_text(encoding="utf-8"))
        self.assertIn(objects, result.skipped_files)

    def test_init_tracks_repair_operation_guidance(self) -> None:
        initialize_project(self.root)

        replay = self.root / "operations" / "replay" / "README.md"
        backfill = self.root / "operations" / "backfill" / "README.md"
        reset = self.root / "operations" / "reset" / "README.md"

        self.assertIn("Bronze", replay.read_text(encoding="utf-8"))
        self.assertIn("Source", backfill.read_text(encoding="utf-8"))
        self.assertIn("candidate", reset.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
