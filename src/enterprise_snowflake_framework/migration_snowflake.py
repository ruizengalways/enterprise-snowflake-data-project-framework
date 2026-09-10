from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Sequence

from .migration_model import (
    DeploymentIdentity,
    HistoryRecord,
    MigrationError,
    MigrationFile,
    SnowCliError,
)

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
      WHERE TABLE_SCHEMA IN ('CONTROL', 'SILVER'))
  + (SELECT COUNT(*) FROM INFORMATION_SCHEMA.PROCEDURES
      WHERE PROCEDURE_SCHEMA IN ('CONTROL', 'SILVER')) AS OBJECT_COUNT"""
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
    ORDER BY STARTED_AT DESC, FINISHED_AT DESC NULLS FIRST, DEPLOYMENT_ATTEMPT_ID DESC
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
