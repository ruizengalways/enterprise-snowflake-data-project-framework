from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
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

BOOTSTRAP_SQL = """CREATE SCHEMA IF NOT EXISTS CONTROL;

CREATE TABLE IF NOT EXISTS CONTROL.DEPLOYMENT_HISTORY (
    DEPLOYMENT_ATTEMPT_ID VARCHAR NOT NULL,
    MIGRATION_SCOPE VARCHAR NOT NULL,
    MIGRATION_PATH VARCHAR NOT NULL,
    CHECKSUM_SHA256 VARCHAR(64) NOT NULL,
    MANIFEST_POSITION NUMBER NOT NULL,
    PROJECT_GIT_SHA VARCHAR(40) NOT NULL,
    FRAMEWORK_GIT_SHA VARCHAR(40) NOT NULL,
    STATUS VARCHAR NOT NULL,
    STARTED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    FINISHED_AT TIMESTAMP_TZ,
    ERROR_CODE VARCHAR,
    ERROR_DETAILS VARCHAR,
    GITHUB_RUN_ID VARCHAR,
    OPERATOR_REASON VARCHAR
);
"""


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


def _sql_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


class SnowCliClient:
    def __init__(self, env: dict[str, str] | None = None):
        self.env = dict(os.environ if env is None else env)
        required = (
            "SNOWFLAKE_ACCOUNT",
            "SNOWFLAKE_USER",
            "SNOWFLAKE_ROLE",
            "SNOWFLAKE_WAREHOUSE",
            "SNOWFLAKE_DATABASE",
        )
        missing = [name for name in required if not self.env.get(name)]
        if missing:
            raise ValueError(f"missing Snowflake connection environment: {', '.join(missing)}")

    def _base_command(self) -> list[str]:
        authenticator = self.env.get("ESF_SNOWFLAKE_AUTHENTICATOR", "WORKLOAD_IDENTITY")
        command = [
            "snow",
            "sql",
            "--temporary-connection",
            "--account",
            self.env["SNOWFLAKE_ACCOUNT"],
            "--user",
            self.env["SNOWFLAKE_USER"],
            "--role",
            self.env["SNOWFLAKE_ROLE"],
            "--warehouse",
            self.env["SNOWFLAKE_WAREHOUSE"],
            "--database",
            self.env["SNOWFLAKE_DATABASE"],
            "--authenticator",
            authenticator,
            "--enable-templating",
            "NONE",
            "--local-only",
            "--enhanced-exit-codes",
            "--silent",
        ]
        provider = self.env.get("ESF_SNOWFLAKE_WORKLOAD_IDENTITY_PROVIDER")
        if authenticator.upper() == "WORKLOAD_IDENTITY":
            command.extend(["--workload-identity-provider", provider or "OIDC"])
        return command

    def _run(self, extra: Sequence[str]) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [*self._base_command(), *extra],
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            details = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
            raise SnowCliError(completed.returncode, details)
        return completed

    def execute_sql(self, sql: str) -> None:
        self._run(["-q", sql])

    def query_json(self, sql: str) -> list[dict[str, object]]:
        completed = self._run(["--format", "JSON", "-q", sql])
        try:
            value = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise MigrationError(f"could not parse Snowflake CLI JSON output: {completed.stdout!r}") from exc
        if not isinstance(value, list):
            raise MigrationError("Snowflake CLI JSON output was not a result list")
        return [row for row in value if isinstance(row, dict)]

    def execute_file(self, path: Path) -> None:
        completed = self._run(["-f", str(path)])
        if completed.stdout.strip():
            print(completed.stdout.strip())


class SnowflakeHistoryStore:
    def __init__(self, client: SnowCliClient):
        self.client = client

    def bootstrap(self) -> None:
        self.client.execute_sql(BOOTSTRAP_SQL)

    def existing_managed_object_count(self) -> int:
        rows = self.client.query_json(
            """SELECT
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
      WHERE TABLE_SCHEMA IN ('CONTROL', 'SILVER')
        AND NOT (TABLE_SCHEMA = 'CONTROL' AND TABLE_NAME = 'DEPLOYMENT_HISTORY'))
  + (SELECT COUNT(*) FROM INFORMATION_SCHEMA.VIEWS
      WHERE TABLE_SCHEMA IN ('CONTROL', 'SILVER')) AS OBJECT_COUNT"""
        )
        if not rows:
            return 0
        return int(rows[0].get("OBJECT_COUNT", 0))

    def latest_history(self) -> tuple[HistoryRecord, ...]:
        rows = self.client.query_json(
            """SELECT
    DEPLOYMENT_ATTEMPT_ID,
    MIGRATION_SCOPE,
    MIGRATION_PATH,
    CHECKSUM_SHA256,
    MANIFEST_POSITION,
    STATUS
FROM CONTROL.DEPLOYMENT_HISTORY
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY MIGRATION_SCOPE, MIGRATION_PATH
    ORDER BY STARTED_AT DESC, DEPLOYMENT_ATTEMPT_ID DESC
) = 1
ORDER BY MIGRATION_SCOPE, MANIFEST_POSITION"""
        )
        records: list[HistoryRecord] = []
        for row in rows:
            records.append(
                HistoryRecord(
                    attempt_id=str(row["DEPLOYMENT_ATTEMPT_ID"]),
                    scope=str(row["MIGRATION_SCOPE"]),
                    path=str(row["MIGRATION_PATH"]),
                    checksum_sha256=str(row["CHECKSUM_SHA256"]),
                    manifest_position=int(row["MANIFEST_POSITION"]),
                    status=str(row["STATUS"]),
                )
            )
        return tuple(records)

    def record_started(self, migration: MigrationFile, identity: DeploymentIdentity) -> str:
        attempt_id = str(uuid.uuid4())
        self.client.execute_sql(
            "INSERT INTO CONTROL.DEPLOYMENT_HISTORY ("
            "DEPLOYMENT_ATTEMPT_ID, MIGRATION_SCOPE, MIGRATION_PATH, CHECKSUM_SHA256, "
            "MANIFEST_POSITION, PROJECT_GIT_SHA, FRAMEWORK_GIT_SHA, STATUS, STARTED_AT, GITHUB_RUN_ID"
            ") SELECT "
            f"{_sql_literal(attempt_id)}, {_sql_literal(migration.scope)}, {_sql_literal(migration.path)}, "
            f"{_sql_literal(migration.checksum_sha256)}, {migration.manifest_position}, "
            f"{_sql_literal(identity.project_git_sha)}, {_sql_literal(identity.framework_git_sha)}, "
            f"'STARTED', CURRENT_TIMESTAMP(), {_sql_literal(identity.github_run_id)}"
        )
        return attempt_id

    def record_succeeded(self, attempt_id: str) -> None:
        self.client.execute_sql(
            "UPDATE CONTROL.DEPLOYMENT_HISTORY SET STATUS = 'SUCCEEDED', "
            "FINISHED_AT = CURRENT_TIMESTAMP(), ERROR_CODE = NULL, ERROR_DETAILS = NULL "
            f"WHERE DEPLOYMENT_ATTEMPT_ID = {_sql_literal(attempt_id)} AND STATUS = 'STARTED'"
        )

    def record_failed(self, attempt_id: str, error_code: str, error_details: str) -> None:
        self.client.execute_sql(
            "UPDATE CONTROL.DEPLOYMENT_HISTORY SET STATUS = 'FAILED', "
            "FINISHED_AT = CURRENT_TIMESTAMP(), "
            f"ERROR_CODE = {_sql_literal(error_code[:256])}, "
            f"ERROR_DETAILS = {_sql_literal(error_details[:16000])} "
            f"WHERE DEPLOYMENT_ATTEMPT_ID = {_sql_literal(attempt_id)} AND STATUS = 'STARTED'"
        )

    def record_baseline(
        self,
        migrations: Sequence[MigrationFile],
        identity: DeploymentIdentity,
        reason: str,
    ) -> None:
        values: list[str] = []
        for migration in migrations:
            values.append(
                "("
                f"{_sql_literal(str(uuid.uuid4()))}, {_sql_literal(migration.scope)}, "
                f"{_sql_literal(migration.path)}, {_sql_literal(migration.checksum_sha256)}, "
                f"{migration.manifest_position}, {_sql_literal(identity.project_git_sha)}, "
                f"{_sql_literal(identity.framework_git_sha)}, 'BASELINED', CURRENT_TIMESTAMP(), "
                f"CURRENT_TIMESTAMP(), {_sql_literal(identity.github_run_id)}, {_sql_literal(reason)}"
                ")"
            )
        self.client.execute_sql(
            "INSERT INTO CONTROL.DEPLOYMENT_HISTORY ("
            "DEPLOYMENT_ATTEMPT_ID, MIGRATION_SCOPE, MIGRATION_PATH, CHECKSUM_SHA256, "
            "MANIFEST_POSITION, PROJECT_GIT_SHA, FRAMEWORK_GIT_SHA, STATUS, STARTED_AT, "
            "FINISHED_AT, GITHUB_RUN_ID, OPERATOR_REASON"
            ") VALUES\n" + ",\n".join(values)
        )

    def record_remediated(
        self,
        migration: MigrationFile,
        identity: DeploymentIdentity,
        reason: str,
    ) -> None:
        self.client.execute_sql(
            "INSERT INTO CONTROL.DEPLOYMENT_HISTORY ("
            "DEPLOYMENT_ATTEMPT_ID, MIGRATION_SCOPE, MIGRATION_PATH, CHECKSUM_SHA256, "
            "MANIFEST_POSITION, PROJECT_GIT_SHA, FRAMEWORK_GIT_SHA, STATUS, STARTED_AT, "
            "FINISHED_AT, GITHUB_RUN_ID, OPERATOR_REASON"
            ") SELECT "
            f"{_sql_literal(str(uuid.uuid4()))}, {_sql_literal(migration.scope)}, "
            f"{_sql_literal(migration.path)}, {_sql_literal(migration.checksum_sha256)}, "
            f"{migration.manifest_position}, {_sql_literal(identity.project_git_sha)}, "
            f"{_sql_literal(identity.framework_git_sha)}, 'REMEDIATED', CURRENT_TIMESTAMP(), "
            f"CURRENT_TIMESTAMP(), {_sql_literal(identity.github_run_id)}, {_sql_literal(reason)}"
        )
