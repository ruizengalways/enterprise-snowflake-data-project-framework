from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from enterprise_snowflake_framework.migration_deployment import (
    DeploymentIdentity,
    HistoryRecord,
    MigrationBlocked,
    MigrationFile,
    MigrationError,
    SnowCliError,
    baseline_existing_migrations,
    deploy_migrations,
    load_migrations,
    remediate_migration,
)


IDENTITY = DeploymentIdentity(
    project_git_sha="1" * 40,
    framework_git_sha="2" * 40,
    github_run_id="12345",
)


class FakeHistoryStore:
    def __init__(self, *, existing_objects: int = 0):
        self.existing_objects = existing_objects
        self.bootstrapped = 0
        self.records: list[HistoryRecord] = []
        self._counter = 0

    def bootstrap(self) -> None:
        self.bootstrapped += 1

    def existing_managed_object_count(self) -> int:
        return self.existing_objects

    def latest_history(self) -> tuple[HistoryRecord, ...]:
        latest: dict[tuple[str, str], HistoryRecord] = {}
        for record in self.records:
            latest[(record.scope, record.path)] = record
        return tuple(latest.values())

    def _attempt_id(self) -> str:
        self._counter += 1
        return f"attempt-{self._counter}"

    def record_started(self, migration: MigrationFile, identity: DeploymentIdentity) -> str:
        attempt_id = self._attempt_id()
        self.records.append(
            HistoryRecord(
                attempt_id=attempt_id,
                scope=migration.scope,
                path=migration.path,
                checksum_sha256=migration.checksum_sha256,
                manifest_position=migration.manifest_position,
                status="STARTED",
            )
        )
        return attempt_id

    def _replace_status(self, attempt_id: str, status: str) -> None:
        for index, record in enumerate(self.records):
            if record.attempt_id == attempt_id:
                self.records[index] = replace(record, status=status)
                return
        raise AssertionError(f"unknown attempt: {attempt_id}")

    def record_succeeded(self, attempt_id: str) -> None:
        self._replace_status(attempt_id, "SUCCEEDED")

    def record_failed(self, attempt_id: str, error_code: str, error_details: str) -> None:
        self._replace_status(attempt_id, "FAILED")

    def record_baseline(
        self,
        migrations: tuple[MigrationFile, ...],
        identity: DeploymentIdentity,
        reason: str,
    ) -> None:
        for migration in migrations:
            self.records.append(
                HistoryRecord(
                    attempt_id=self._attempt_id(),
                    scope=migration.scope,
                    path=migration.path,
                    checksum_sha256=migration.checksum_sha256,
                    manifest_position=migration.manifest_position,
                    status="BASELINED",
                )
            )

    def record_remediated(
        self,
        migration: MigrationFile,
        identity: DeploymentIdentity,
        reason: str,
    ) -> None:
        self.records.append(
            HistoryRecord(
                attempt_id=self._attempt_id(),
                scope=migration.scope,
                path=migration.path,
                checksum_sha256=migration.checksum_sha256,
                manifest_position=migration.manifest_position,
                status="REMEDIATED",
            )
        )


class FakeExecutor:
    def __init__(self, *, fail_paths: set[str] | None = None):
        self.fail_paths = fail_paths or set()
        self.executed: list[str] = []

    def execute_file(self, path: Path) -> None:
        normalized = path.as_posix()
        self.executed.append(normalized)
        if any(normalized.endswith(value) for value in self.fail_paths):
            raise SnowCliError(5, "synthetic migration failure")


class MigrationDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "domain"
        (self.root / "control_plane/sql").mkdir(parents=True)
        (self.root / "silver_processing/source/customer").mkdir(parents=True)
        (self.root / "control_plane/sql/001_objects.sql").write_text("select 'control';\n", encoding="utf-8")
        (self.root / "silver_processing/source/customer/001_objects.sql").write_text(
            "select 'silver';\n", encoding="utf-8"
        )
        (self.root / "control_plane/deploy_manifest.txt").write_text(
            "control_plane/sql/001_objects.sql\n", encoding="utf-8"
        )
        (self.root / "silver_processing/deploy_manifest.txt").write_text(
            "silver_processing/source/customer/001_objects.sql\n", encoding="utf-8"
        )

    def test_first_deploy_applies_every_migration_and_records_success(self) -> None:
        store = FakeHistoryStore(existing_objects=0)
        executor = FakeExecutor()

        result = deploy_migrations(self.root, IDENTITY, store, executor)

        self.assertEqual(2, len(result.applied))
        self.assertEqual((), result.skipped)
        self.assertEqual(2, len(executor.executed))
        self.assertEqual({"SUCCEEDED"}, {record.status for record in store.latest_history()})

    def test_repeat_deploy_of_same_files_executes_zero_migrations(self) -> None:
        store = FakeHistoryStore(existing_objects=0)
        first = FakeExecutor()
        deploy_migrations(self.root, IDENTITY, store, first)

        second = FakeExecutor()
        result = deploy_migrations(self.root, IDENTITY, store, second)

        self.assertEqual((), result.applied)
        self.assertEqual(2, len(result.skipped))
        self.assertEqual([], second.executed)

    def test_changed_checksum_of_applied_migration_blocks(self) -> None:
        store = FakeHistoryStore(existing_objects=0)
        deploy_migrations(self.root, IDENTITY, store, FakeExecutor())
        changed = self.root / "silver_processing/source/customer/001_objects.sql"
        changed.write_text("select 'changed';\n", encoding="utf-8")

        executor = FakeExecutor()
        with self.assertRaises(MigrationBlocked) as ctx:
            deploy_migrations(self.root, IDENTITY, store, executor)

        self.assertTrue(any("checksum changed" in item for item in ctx.exception.errors))
        self.assertEqual([], executor.executed)

    def test_failed_migration_is_recorded_and_next_deploy_blocks_without_retry(self) -> None:
        store = FakeHistoryStore(existing_objects=0)
        failing = FakeExecutor(fail_paths={"silver_processing/source/customer/001_objects.sql"})

        with self.assertRaises(MigrationError):
            deploy_migrations(self.root, IDENTITY, store, failing)

        latest = {(item.scope, item.path): item for item in store.latest_history()}
        self.assertEqual("SUCCEEDED", latest[("CONTROL", "control_plane/sql/001_objects.sql")].status)
        self.assertEqual(
            "FAILED",
            latest[("SILVER", "silver_processing/source/customer/001_objects.sql")].status,
        )

        second = FakeExecutor()
        with self.assertRaises(MigrationBlocked) as ctx:
            deploy_migrations(self.root, IDENTITY, store, second)
        self.assertTrue(any("unresolved FAILED" in item for item in ctx.exception.errors))
        self.assertEqual([], second.executed)

    def test_existing_domain_without_history_requires_explicit_baseline(self) -> None:
        store = FakeHistoryStore(existing_objects=12)
        executor = FakeExecutor()

        with self.assertRaises(MigrationBlocked) as ctx:
            deploy_migrations(self.root, IDENTITY, store, executor)

        self.assertTrue(any("explicitly reviewed baseline" in item for item in ctx.exception.errors))
        self.assertEqual([], executor.executed)

    def test_baseline_existing_domain_records_files_without_executing_them(self) -> None:
        store = FakeHistoryStore(existing_objects=12)

        paths = baseline_existing_migrations(
            self.root,
            IDENTITY,
            store,
            reason="adopt existing production state",
            confirmed=True,
        )

        self.assertEqual(2, len(paths))
        self.assertEqual({"BASELINED"}, {record.status for record in store.latest_history()})
        executor = FakeExecutor()
        result = deploy_migrations(self.root, IDENTITY, store, executor)
        self.assertEqual((), result.applied)
        self.assertEqual(2, len(result.skipped))
        self.assertEqual([], executor.executed)

    def test_baseline_is_not_allowed_for_a_fresh_empty_domain(self) -> None:
        store = FakeHistoryStore(existing_objects=0)
        with self.assertRaises(MigrationBlocked):
            baseline_existing_migrations(
                self.root,
                IDENTITY,
                store,
                reason="do not do this",
                confirmed=True,
            )

    def test_manifest_reordering_of_applied_migration_blocks(self) -> None:
        extra = self.root / "silver_processing/source/customer/010_apply.sql"
        extra.write_text("select 'apply';\n", encoding="utf-8")
        manifest = self.root / "silver_processing/deploy_manifest.txt"
        manifest.write_text(
            "silver_processing/source/customer/001_objects.sql\n"
            "silver_processing/source/customer/010_apply.sql\n",
            encoding="utf-8",
        )
        store = FakeHistoryStore(existing_objects=0)
        deploy_migrations(self.root, IDENTITY, store, FakeExecutor())

        manifest.write_text(
            "silver_processing/source/customer/010_apply.sql\n"
            "silver_processing/source/customer/001_objects.sql\n",
            encoding="utf-8",
        )
        with self.assertRaises(MigrationBlocked) as ctx:
            deploy_migrations(self.root, IDENTITY, store, FakeExecutor())
        self.assertTrue(any("changed manifest position" in item for item in ctx.exception.errors))

    def test_removing_applied_migration_from_manifest_blocks(self) -> None:
        store = FakeHistoryStore(existing_objects=0)
        deploy_migrations(self.root, IDENTITY, store, FakeExecutor())
        (self.root / "silver_processing/deploy_manifest.txt").write_text(
            "silver_processing/source/customer/010_new.sql\n", encoding="utf-8"
        )
        (self.root / "silver_processing/source/customer/010_new.sql").write_text(
            "select 'new';\n", encoding="utf-8"
        )

        with self.assertRaises(MigrationBlocked) as ctx:
            deploy_migrations(self.root, IDENTITY, store, FakeExecutor())
        self.assertTrue(any("removed from its manifest" in item for item in ctx.exception.errors))

    def test_explicit_remediation_unblocks_failed_file_without_reexecuting_it(self) -> None:
        store = FakeHistoryStore(existing_objects=0)
        failing = FakeExecutor(fail_paths={"silver_processing/source/customer/001_objects.sql"})
        with self.assertRaises(MigrationError):
            deploy_migrations(self.root, IDENTITY, store, failing)

        path = remediate_migration(
            self.root,
            IDENTITY,
            store,
            migration_path="silver_processing/source/customer/001_objects.sql",
            reason="verified partial DDL state and repaired manually",
            confirmed=True,
        )
        self.assertEqual("silver_processing/source/customer/001_objects.sql", path)

        executor = FakeExecutor()
        result = deploy_migrations(self.root, IDENTITY, store, executor)
        self.assertEqual((), result.applied)
        self.assertEqual(2, len(result.skipped))
        self.assertEqual([], executor.executed)

    def test_load_migrations_rejects_duplicate_and_unsafe_paths(self) -> None:
        (self.root / "silver_processing/deploy_manifest.txt").write_text(
            "silver_processing/source/customer/001_objects.sql\n"
            "silver_processing/source/customer/001_objects.sql\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "duplicate migration path"):
            load_migrations(self.root)

        (self.root / "silver_processing/deploy_manifest.txt").write_text(
            "silver_processing/../secrets.sql\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "unsafe migration path"):
            load_migrations(self.root)


if __name__ == "__main__":
    unittest.main()
