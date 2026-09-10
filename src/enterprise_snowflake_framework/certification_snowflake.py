from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .certification_project import CertificationProject, build_certification_project
from .migration_snowflake import SnowCliClient
from .pipeline_model import PipelineNames, build_names

CERT_DATABASE = "CI_FRAMEWORK_CERT"
CERT_ROLE = "AR_FRAMEWORK_CERT"
CERT_USER = "SU_GITHUB_FRAMEWORK_CERT"
CERT_WAREHOUSE = "WH_FRAMEWORK_CERT_TRANSFORM"
TERMINAL_TASK_FAILURES = {"FAILED", "FAILED_AND_AUTO_SUSPENDED", "CANCELLED"}


class CertificationFailure(RuntimeError):
    pass


@dataclass
class CertificationReport:
    framework_git_sha: str
    framework_version: str
    snowflake_version: str = "UNKNOWN"
    database: str = CERT_DATABASE
    status: str = "RUNNING"
    checks: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def pass_check(self, name: str) -> None:
        self.checks[name] = "PASS"

    def fail(self, error: BaseException) -> None:
        self.status = "FAILED"
        self.error = str(error)

    def complete(self) -> None:
        self.status = "CERTIFIED"
        self.checks.setdefault("dynamic_table", "NOT_APPLICABLE")

    def write(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "framework_git_sha": self.framework_git_sha,
            "framework_version": self.framework_version,
            "snowflake_version": self.snowflake_version,
            "database": self.database,
            "status": self.status,
            "checks": self.checks,
            "error": self.error,
        }
        (output_dir / "snowflake-certification.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        lines = [
            "# Snowflake certification result",
            "",
            f"- Status: **{self.status}**",
            f"- Framework version: `{self.framework_version}`",
            f"- Framework Git SHA: `{self.framework_git_sha}`",
            f"- Snowflake version: `{self.snowflake_version}`",
            f"- Certification database: `{self.database}`",
            "",
            "## Checks",
            "",
        ]
        lines.extend(f"- `{name}`: **{status}**" for name, status in sorted(self.checks.items()))
        if self.error:
            lines.extend(["", "## Failure", "", f"`{self.error}`"])
        (output_dir / "snowflake-certification.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _row_value(row: dict[str, object], name: str) -> object | None:
    for candidate in (name, name.upper(), name.lower()):
        if candidate in row:
            return row[candidate]
    for key, value in row.items():
        if key.upper() == name.upper():
            return value
    return None


def _sql_literal(value: object, snowflake_type: str) -> str:
    if value is None:
        return "NULL"
    upper_type = snowflake_type.upper()
    if upper_type.startswith("NUMBER") or upper_type.startswith("INT"):
        return str(value)
    escaped = str(value).replace("'", "''")
    if upper_type.startswith("TIMESTAMP_NTZ"):
        return f"TO_TIMESTAMP_NTZ('{escaped}')"
    if upper_type.startswith("TIMESTAMP_LTZ"):
        return f"TO_TIMESTAMP_LTZ('{escaped}')"
    if upper_type.startswith("BOOLEAN"):
        return "TRUE" if bool(value) else "FALSE"
    return f"'{escaped}'"


def _required_environment(env: dict[str, str]) -> None:
    expected = {
        "SNOWFLAKE_DATABASE": CERT_DATABASE,
        "SNOWFLAKE_ROLE": CERT_ROLE,
        "SNOWFLAKE_USER": CERT_USER,
        "SNOWFLAKE_WAREHOUSE": CERT_WAREHOUSE,
    }
    mismatches = [
        f"{key} must be {value!r}, got {env.get(key)!r}"
        for key, value in expected.items()
        if env.get(key) != value
    ]
    if mismatches:
        raise CertificationFailure("unsafe certification environment: " + "; ".join(mismatches))


def reset_certification_schemas(client: SnowCliClient) -> None:
    _required_environment(client.env)
    client.execute_sql(
        "DROP SCHEMA IF EXISTS SILVER CASCADE;\n"
        "DROP SCHEMA IF EXISTS BRONZE CASCADE;\n"
        "DROP SCHEMA IF EXISTS CONTROL CASCADE;\n"
        "CREATE TRANSIENT SCHEMA BRONZE;\n"
        "CREATE TRANSIENT SCHEMA SILVER;\n"
        "CREATE TRANSIENT SCHEMA CONTROL;"
    )


def cleanup_certification_schemas(client: SnowCliClient) -> None:
    _required_environment(client.env)
    client.execute_sql(
        "DROP SCHEMA IF EXISTS SILVER CASCADE;\n"
        "DROP SCHEMA IF EXISTS BRONZE CASCADE;\n"
        "DROP SCHEMA IF EXISTS CONTROL CASCADE;"
    )


class SnowflakeCertificationRuntime:
    def __init__(
        self,
        *,
        client: SnowCliClient,
        framework_git_sha: str,
        report: CertificationReport,
        project: CertificationProject,
    ) -> None:
        self.client = client
        self.framework_git_sha = framework_git_sha
        self.report = report
        self.project = project
        self.cert_role = CERT_ROLE

    def fail(self, message: str) -> None:
        raise CertificationFailure(message)

    def query_one(self, sql: str) -> dict[str, object]:
        rows = self.client.query_json(sql)
        if len(rows) != 1:
            self.fail(f"expected exactly one Snowflake result row, got {len(rows)}: {sql}")
        return rows[0]

    def assert_scalar(self, sql: str, expected: object, column: str = "ACTUAL") -> None:
        row = self.query_one(sql)
        actual = _row_value(row, column)
        if str(actual) != str(expected):
            self.fail(f"assertion failed: expected {expected!r}, got {actual!r}; SQL={sql}")

    def names(self, dataset_id: str, pattern: str, version: str = "v1") -> PipelineNames:
        return build_names(
            source_id=self.project.source_id,
            dataset_id=dataset_id,
            pattern=pattern,
            entity=dataset_id,
            version=version,
        )

    def dataset_spec(self, dataset_id: str) -> dict[str, Any]:
        value = self.project.fixture["datasets"][dataset_id]
        if not isinstance(value, dict):
            self.fail(f"invalid fixture dataset: {dataset_id}")
        return value

    def create_bronze_tables(self) -> None:
        for dataset_id, spec in self.project.fixture["datasets"].items():
            contract = spec["contract"]
            columns = []
            for column in contract["columns"]:
                nullable = "" if column.get("nullable", True) else " NOT NULL"
                columns.append(f"{str(column['name']).upper()} {column['type']}{nullable}")
            names = self.names(str(dataset_id), str(spec["pattern"]))
            self.client.execute_sql(f"CREATE TABLE {names.bronze_relation} (" + ", ".join(columns) + ");")

    def insert_rows(self, dataset_id: str, rows: list[dict[str, Any]], *, replace: bool = False) -> None:
        spec = self.dataset_spec(dataset_id)
        names = self.names(dataset_id, str(spec["pattern"]))
        contract = spec["contract"]
        columns = [str(column["name"]).upper() for column in contract["columns"]]
        types = {str(column["name"]).upper(): str(column["type"]) for column in contract["columns"]}
        if replace:
            self.client.execute_sql(f"DELETE FROM {names.bronze_relation};")
        if not rows:
            return
        values = []
        for row in rows:
            rendered = [_sql_literal(row.get(column.lower()), types[column]) for column in columns]
            values.append("(" + ", ".join(rendered) + ")")
        self.client.execute_sql(
            f"INSERT INTO {names.bronze_relation} ({', '.join(columns)}) VALUES " + ", ".join(values) + ";"
        )

    def call_apply(self, names: PipelineNames) -> None:
        self.client.execute_sql(f"CALL {names.apply_procedure}();")

    def call_validate(self, names: PipelineNames) -> None:
        self.client.execute_sql(f"CALL {names.validate_procedure}();")

    def run_migrate(self, project_sha: str, expected_code: int = 0) -> str:
        env = dict(self.client.env)
        env["ESF_FRAMEWORK_GIT_SHA"] = self.framework_git_sha
        completed = subprocess.run(
            [
                "esf-migrate",
                "deploy",
                "--project-root",
                str(self.project.root),
                "--project-git-sha",
                project_sha,
                "--framework-git-sha",
                self.framework_git_sha,
                "--github-run-id",
                env.get("GITHUB_RUN_ID", "local-certification"),
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        if completed.returncode != expected_code:
            self.fail(f"esf-migrate returned {completed.returncode}, expected {expected_code}: {output}")
        return output

    def poll_task(self, task_name: str, scheduled_from: str, timeout_seconds: int = 90) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            rows = self.client.query_json(
                "SELECT STATE, SCHEDULED_FROM, ERROR_MESSAGE, QUERY_ID "
                "FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY("
                "SCHEDULED_TIME_RANGE_START=>DATEADD('minute', -5, CURRENT_TIMESTAMP()), "
                "RESULT_LIMIT=>20, "
                f"TASK_NAME=>'{task_name}', DATABASE_NAME=>'{CERT_DATABASE}', SCHEMA_NAME=>'SILVER')) "
                "WHERE QUERY_ID IS NOT NULL ORDER BY SCHEDULED_TIME DESC"
            )
            for row in rows:
                if str(_row_value(row, "SCHEDULED_FROM") or "").upper() != scheduled_from.upper():
                    continue
                state = str(_row_value(row, "STATE") or "").upper()
                if state == "SUCCEEDED":
                    return
                if state in TERMINAL_TASK_FAILURES:
                    self.fail(f"task {task_name} ended {state}: {_row_value(row, 'ERROR_MESSAGE')}")
            time.sleep(2)
        self.fail(f"timed out waiting for {task_name} task run from {scheduled_from}")

    def assert_published_select_grant(self, published_view: str) -> None:
        view_name = published_view.split(".", 1)[1]
        self.assert_scalar(
            "SELECT COUNT(*) AS ACTUAL FROM INFORMATION_SCHEMA.OBJECT_PRIVILEGES "
            f"WHERE OBJECT_SCHEMA='SILVER' AND OBJECT_NAME='{view_name}' "
            f"AND GRANTEE='{CERT_ROLE}' AND PRIVILEGE_TYPE='SELECT'",
            1,
        )


class SnowflakeCertifier:
    def __init__(
        self,
        *,
        client: SnowCliClient,
        framework_git_sha: str,
        framework_version: str,
        fixture_path: Path,
        workspace_root: Path,
        output_dir: Path,
    ) -> None:
        _required_environment(client.env)
        self.client = client
        self.framework_git_sha = framework_git_sha
        self.fixture_path = fixture_path.resolve()
        self.workspace_root = workspace_root.resolve()
        self.output_dir = output_dir.resolve()
        self.report = CertificationReport(
            framework_git_sha=framework_git_sha,
            framework_version=framework_version,
        )

    def run(self) -> CertificationReport:
        try:
            identity_rows = self.client.query_json(
                "SELECT CURRENT_DATABASE() AS DB, CURRENT_ROLE() AS ROLE, CURRENT_WAREHOUSE() AS WH, "
                "CURRENT_VERSION() AS SNOWFLAKE_VERSION"
            )
            if len(identity_rows) != 1:
                raise CertificationFailure("could not resolve Snowflake certification session identity")
            identity = identity_rows[0]
            if str(_row_value(identity, "DB")) != CERT_DATABASE:
                raise CertificationFailure("Snowflake current database does not match certification database")
            if str(_row_value(identity, "ROLE")) != CERT_ROLE:
                raise CertificationFailure("Snowflake current role does not match certification role")
            if str(_row_value(identity, "WH")) != CERT_WAREHOUSE:
                raise CertificationFailure("Snowflake current warehouse does not match certification warehouse")
            self.report.snowflake_version = str(_row_value(identity, "SNOWFLAKE_VERSION") or "UNKNOWN")

            reset_certification_schemas(self.client)
            project = build_certification_project(self.workspace_root, self.fixture_path)
            runtime = SnowflakeCertificationRuntime(
                client=self.client,
                framework_git_sha=self.framework_git_sha,
                report=self.report,
                project=project,
            )
            runtime.create_bronze_tables()

            first = runtime.run_migrate(project.project_git_sha)
            if "Applied: 0" in first:
                runtime.fail("fresh certification deployment unexpectedly applied zero migrations")
            repeat = runtime.run_migrate(project.project_git_sha)
            if "Applied: 0" not in repeat:
                runtime.fail(f"repeat migration deployment was not a zero-apply run: {repeat}")
            self.report.pass_check("apply_once_first_deploy")
            self.report.pass_check("apply_once_repeat_deploy")

            from .certification_scenarios import run_all_scenarios

            run_all_scenarios(runtime)
            self.report.complete()
            return self.report
        except BaseException as exc:
            self.report.fail(exc)
            raise
        finally:
            self.report.write(self.output_dir)
