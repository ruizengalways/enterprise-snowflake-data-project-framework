from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, Sequence

MIGRATION_MANIFESTS = (
    ("CONTROL", "control_plane/deploy_manifest.txt", "control_plane/"),
    ("SILVER", "silver_processing/deploy_manifest.txt", "silver_processing/"),
)
TERMINAL_SUCCESS_STATUSES = frozenset({"SUCCEEDED", "BASELINED", "REMEDIATED"})
BLOCKING_STATUSES = frozenset({"STARTED", "FAILED"})
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./-]+\.sql$")


class MigrationError(RuntimeError):
    """Base migration deployment error."""


class MigrationBlocked(MigrationError):
    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


class SnowCliError(MigrationError):
    def __init__(self, returncode: int, details: str):
        self.returncode = returncode
        self.details = details.strip()
        super().__init__(self.details or f"snow sql failed with exit code {returncode}")


@dataclass(frozen=True)
class DeploymentIdentity:
    project_git_sha: str
    framework_git_sha: str
    github_run_id: str | None = None

    def validate(self) -> None:
        if not _GIT_SHA_RE.fullmatch(self.project_git_sha):
            raise ValueError("project_git_sha must be a lowercase 40-character Git SHA")
        if not _GIT_SHA_RE.fullmatch(self.framework_git_sha):
            raise ValueError("framework_git_sha must be a lowercase 40-character Git SHA")


@dataclass(frozen=True)
class MigrationFile:
    scope: str
    path: str
    manifest_position: int
    checksum_sha256: str
    absolute_path: Path


@dataclass(frozen=True)
class HistoryRecord:
    attempt_id: str
    scope: str
    path: str
    checksum_sha256: str
    manifest_position: int
    status: str


@dataclass(frozen=True)
class MigrationDecision:
    migration: MigrationFile
    action: str
    reason: str


@dataclass(frozen=True)
class MigrationPlan:
    decisions: tuple[MigrationDecision, ...]
    errors: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class DeploymentResult:
    applied: tuple[str, ...]
    skipped: tuple[str, ...]


class HistoryStore(Protocol):
    def bootstrap(self) -> None: ...

    def existing_managed_object_count(self) -> int: ...

    def latest_history(self) -> tuple[HistoryRecord, ...]: ...

    def record_started(self, migration: MigrationFile, identity: DeploymentIdentity) -> str: ...

    def record_succeeded(self, attempt_id: str) -> None: ...

    def record_failed(self, attempt_id: str, error_code: str, error_details: str) -> None: ...

    def record_baseline(
        self,
        migrations: Sequence[MigrationFile],
        identity: DeploymentIdentity,
        reason: str,
    ) -> None: ...

    def record_remediated(
        self,
        migration: MigrationFile,
        identity: DeploymentIdentity,
        reason: str,
    ) -> None: ...


class MigrationExecutor(Protocol):
    def execute_file(self, path: Path) -> None: ...


def _validate_migration_path(value: str, prefix: str) -> None:
    if not value.startswith(prefix):
        raise ValueError(f"migration path must start with {prefix}: {value}")
    if not _SAFE_PATH_RE.fullmatch(value):
        raise ValueError(f"unsafe migration path: {value}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise ValueError(f"unsafe migration path: {value}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_migrations(project_root: Path) -> tuple[MigrationFile, ...]:
    project_root = project_root.resolve()
    migrations: list[MigrationFile] = []
    seen_paths: set[str] = set()

    for scope, manifest_rel, prefix in MIGRATION_MANIFESTS:
        manifest = project_root / manifest_rel
        if not manifest.is_file():
            raise ValueError(f"deployment manifest not found: {manifest}")

        position = 0
        for raw in manifest.read_text(encoding="utf-8").splitlines():
            value = raw.split("#", 1)[0].strip()
            if not value:
                continue
            position += 1
            _validate_migration_path(value, prefix)
            if value in seen_paths:
                raise ValueError(f"duplicate migration path across manifests: {value}")
            seen_paths.add(value)
            absolute = project_root / value
            if not absolute.is_file():
                raise ValueError(f"migration file not found: {value}")
            migrations.append(
                MigrationFile(
                    scope=scope,
                    path=value,
                    manifest_position=position,
                    checksum_sha256=sha256_file(absolute),
                    absolute_path=absolute,
                )
            )

        if position == 0:
            raise ValueError(f"deployment manifest contains no migrations: {manifest}")

    return tuple(migrations)


def build_migration_plan(
    migrations: Sequence[MigrationFile],
    history: Sequence[HistoryRecord],
) -> MigrationPlan:
    current = {(item.scope, item.path): item for item in migrations}
    latest = {(item.scope, item.path): item for item in history}
    errors: list[str] = []

    for key, record in latest.items():
        migration = current.get(key)
        if migration is None:
            errors.append(
                f"previously recorded migration was removed from its manifest: {record.scope} {record.path}"
            )
            continue
        if migration.manifest_position != record.manifest_position:
            errors.append(
                "previously recorded migration changed manifest position: "
                f"{record.scope} {record.path} was {record.manifest_position}, "
                f"now {migration.manifest_position}"
            )
        if migration.checksum_sha256 != record.checksum_sha256:
            errors.append(
                f"checksum changed for previously recorded migration: {record.scope} {record.path}"
            )
        status = record.status.upper()
        if status in BLOCKING_STATUSES:
            errors.append(
                f"migration has unresolved {status} attempt: {record.scope} {record.path}; "
                "review partial state and explicitly remediate it before another deployment"
            )
        elif status not in TERMINAL_SUCCESS_STATUSES:
            errors.append(
                f"migration has unsupported history status {status}: {record.scope} {record.path}"
            )

    decisions: list[MigrationDecision] = []
    for migration in migrations:
        record = latest.get((migration.scope, migration.path))
        if record is None:
            decisions.append(MigrationDecision(migration, "APPLY", "new migration"))
            continue
        if record.status.upper() in TERMINAL_SUCCESS_STATUSES:
            decisions.append(MigrationDecision(migration, "SKIP", f"already {record.status.upper()}"))
        else:
            decisions.append(MigrationDecision(migration, "BLOCK", f"latest status is {record.status.upper()}"))

    return MigrationPlan(decisions=tuple(decisions), errors=tuple(dict.fromkeys(errors)))


def deploy_migrations(
    project_root: Path,
    identity: DeploymentIdentity,
    store: HistoryStore,
    executor: MigrationExecutor,
) -> DeploymentResult:
    identity.validate()
    migrations = load_migrations(project_root)
    existing_objects = store.existing_managed_object_count()
    store.bootstrap()
    history = store.latest_history()

    if not history and existing_objects > 0:
        raise MigrationBlocked(
            (
                "existing CONTROL/SILVER objects were detected but deployment history is empty; "
                "run an explicitly reviewed baseline before adopting apply-once deployment",
            )
        )

    plan = build_migration_plan(migrations, history)
    if not plan.ready:
        raise MigrationBlocked(plan.errors)

    applied: list[str] = []
    skipped: list[str] = []
    for decision in plan.decisions:
        migration = decision.migration
        if decision.action == "SKIP":
            skipped.append(migration.path)
            continue
        if decision.action != "APPLY":
            raise MigrationBlocked((f"blocked migration: {migration.path}",))

        attempt_id = store.record_started(migration, identity)
        try:
            executor.execute_file(migration.absolute_path)
        except Exception as exc:
            if isinstance(exc, SnowCliError):
                error_code = str(exc.returncode)
                error_details = exc.details
            else:
                error_code = type(exc).__name__
                error_details = str(exc)
            try:
                store.record_failed(attempt_id, error_code, error_details)
            except Exception as history_exc:
                raise MigrationError(
                    f"migration failed and failure recording also failed for {migration.path}: "
                    f"migration={error_details}; history={history_exc}"
                ) from exc
            raise MigrationError(f"migration failed: {migration.path}: {error_details}") from exc

        store.record_succeeded(attempt_id)
        applied.append(migration.path)

    return DeploymentResult(applied=tuple(applied), skipped=tuple(skipped))


def baseline_existing_migrations(
    project_root: Path,
    identity: DeploymentIdentity,
    store: HistoryStore,
    *,
    reason: str,
    confirmed: bool,
) -> tuple[str, ...]:
    identity.validate()
    if not confirmed:
        raise ValueError("baseline requires --confirm-existing-state-reviewed")
    if not reason.strip():
        raise ValueError("baseline requires a non-empty operator reason")

    migrations = load_migrations(project_root)
    existing_objects = store.existing_managed_object_count()
    if existing_objects == 0:
        raise MigrationBlocked(("no existing CONTROL/SILVER objects detected; use normal first deployment instead",))

    store.bootstrap()
    history = store.latest_history()
    if history:
        raise MigrationBlocked(("deployment history is not empty; baseline is only allowed for first adoption",))

    store.record_baseline(migrations, identity, reason.strip())
    return tuple(item.path for item in migrations)


def remediate_migration(
    project_root: Path,
    identity: DeploymentIdentity,
    store: HistoryStore,
    *,
    migration_path: str,
    reason: str,
    confirmed: bool,
) -> str:
    identity.validate()
    if not confirmed:
        raise ValueError("remediation requires --confirm-partial-state-reviewed")
    if not reason.strip():
        raise ValueError("remediation requires a non-empty operator reason")

    migrations = load_migrations(project_root)
    current = {item.path: item for item in migrations}
    migration = current.get(migration_path)
    if migration is None:
        raise MigrationBlocked((f"migration is not present in current manifests: {migration_path}",))

    store.bootstrap()
    latest = {(item.scope, item.path): item for item in store.latest_history()}
    record = latest.get((migration.scope, migration.path))
    if record is None or record.status.upper() not in BLOCKING_STATUSES:
        raise MigrationBlocked((f"migration does not have a STARTED/FAILED attempt: {migration_path}",))
    if record.checksum_sha256 != migration.checksum_sha256:
        raise MigrationBlocked((f"migration checksum changed since the failed/started attempt: {migration_path}",))
    if record.manifest_position != migration.manifest_position:
        raise MigrationBlocked((f"migration manifest position changed since the failed/started attempt: {migration_path}",))

    store.record_remediated(migration, identity, reason.strip())
    return migration.path
