import unittest

from scripts.check_released_control_migrations import changed_released_control_migrations


class ReleasedControlMigrationImmutabilityTests(unittest.TestCase):
    def test_new_numbered_control_migration_is_allowed(self) -> None:
        diff = (
            "A\tsrc/enterprise_snowflake_framework/templates/project/"
            "control_plane_090_new_feature.sql\n"
        )
        self.assertEqual((), changed_released_control_migrations(diff))

    def test_modifying_released_numbered_control_migration_is_blocked(self) -> None:
        diff = (
            "M\tsrc/enterprise_snowflake_framework/templates/project/"
            "control_plane_080_data_quality_reconciliation.sql\n"
        )
        result = changed_released_control_migrations(diff)
        self.assertEqual(1, len(result))
        self.assertIn("080_data_quality_reconciliation.sql", result[0])

    def test_delete_or_rename_of_released_migration_is_blocked(self) -> None:
        deleted = (
            "D\tsrc/enterprise_snowflake_framework/templates/project/"
            "control_plane_070_enterprise_health_export.sql\n"
        )
        renamed = (
            "R100\tsrc/enterprise_snowflake_framework/templates/project/"
            "control_plane_060_run_evidence_api.sql\t"
            "src/enterprise_snowflake_framework/templates/project/"
            "control_plane_061_run_evidence_api.sql\n"
        )
        self.assertEqual(1, len(changed_released_control_migrations(deleted)))
        self.assertGreaterEqual(len(changed_released_control_migrations(renamed)), 1)

    def test_non_migration_template_changes_are_ignored(self) -> None:
        diff = (
            "M\tREADME.md\n"
            "M\tsrc/enterprise_snowflake_framework/templates/scd2/010_apply.sql\n"
        )
        self.assertEqual((), changed_released_control_migrations(diff))


if __name__ == "__main__":
    unittest.main()
