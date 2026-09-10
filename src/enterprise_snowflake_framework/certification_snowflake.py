from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .certification_project import CertificationProject, add_scd2_candidate, build_certification_project
from .migration_snowflake import SnowCliClient
from .pipeline_model import PipelineNames, build_names
from .versioning import generate_release_scripts

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
    client.execute_sql(
        "DROP SCHEMA IF EXISTS SILVER CASCADE;\n"
        "DROP SCHEMA IF EXISTS BRONZE CASCADE;\n"
        "DROP SCHEMA IF EXISTS CONTROL CASCADE;\n"
        "CREATE TRANSIENT SCHEMA BRONZE;\n"
        "CREATE TRANSIENT SCHEMA SILVER;\n"
        "CREATE TRANSIENT SCHEMA CONTROL;"
    )


def cleanup_certification_schemas(client: SnowCliClient) -> None:
    client.execute_sql(
        "DROP SCHEMA IF EXISTS SILVER CASCADE;\n"
        "DROP SCHEMA IF EXISTS BRONZE CASCADE;\n"
        "DROP SCHEMA IF EXISTS CONTROL CASCADE;"
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
        self.project: CertificationProject | None = None

    def _query_one(self, sql: str) -> dict[str, object]:
        rows = self.client.query_json(sql)
        if len(rows) != 1:
            raise CertificationFailure(f"expected exactly one Snowflake result row, got {len(rows)}: {sql}")
        return rows[0]

    def _assert_scalar(self, sql: str, expected: object, column: str = "ACTUAL") -> None:
        row = self._query_one(sql)
        actual = _row_value(row, column)
        if str(actual) != str(expected):
            raise CertificationFailure(f"assertion failed: expected {expected!r}, got {actual!r}; SQL={sql}")

    def _names(self, dataset_id: str, pattern: str, version: str = "v1") -> PipelineNames:
        assert self.project is not None
        return build_names(
            source_id=self.project.source_id,
            dataset_id=dataset_id,
            pattern=pattern,
            entity=dataset_id,
            version=version,
        )

    def _dataset_spec(self, dataset_id: str) -> dict[str, Any]:
        assert self.project is not None
        value = self.project.fixture["datasets"][dataset_id]
        if not isinstance(value, dict):
            raise CertificationFailure(f"invalid fixture dataset: {dataset_id}")
        return value

    def _create_bronze_tables(self) -> None:
        assert self.project is not None
        for dataset_id, spec in self.project.fixture["datasets"].items():
            contract = spec["contract"]
            columns = []
            for column in contract["columns"]:
                nullable = "" if column.get("nullable", True) else " NOT NULL"
                columns.append(f"{str(column['name']).upper()} {column['type']}{nullable}")
            names = self._names(str(dataset_id), str(spec["pattern"]))
            self.client.execute_sql(f"CREATE TABLE {names.bronze_relation} (" + ", ".join(columns) + ");")

    def _insert_rows(self, dataset_id: str, rows: list[dict[str, Any]], *, replace: bool = False) -> None:
        spec = self._dataset_spec(dataset_id)
        names = self._names(dataset_id, str(spec["pattern"]))
        contract = spec["contract"]
        columns = [str(column["name"]).upper() for column in contract["columns"]]
        types = {str(column["name"]).upper(): str(column["type"]) for column in contract["columns"]}
        if replace:
            self.client.execute_sql(f"DELETE FROM {names.bronze_relation};")
        if not rows:
            return
        values = []
        for row in rows:
            rendered = [
                _sql_literal(row.get(column.lower()), types[column])
                for column in columns
            ]
            values.append("(" + ", ".join(rendered) + ")")
        self.client.execute_sql(
            f"INSERT INTO {names.bronze_relation} ({', '.join(columns)}) VALUES " + ", ".join(values) + ";"
        )

    def _call_apply(self, names: PipelineNames) -> None:
        self.client.execute_sql(f"CALL {names.apply_procedure}();")

    def _call_validate(self, names: PipelineNames) -> None:
        self.client.execute_sql(f"CALL {names.validate_procedure}();")

    def _run_migrate(self, project_sha: str, expected_code: int = 0) -> str:
        assert self.project is not None
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
            raise CertificationFailure(
                f"esf-migrate returned {completed.returncode}, expected {expected_code}: {output}"
            )
        return output

    def _poll_task(self, task_name: str, scheduled_from: str, timeout_seconds: int = 90) -> None:
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
                source = str(_row_value(row, "SCHEDULED_FROM") or "").upper()
                if source != scheduled_from.upper():
                    continue
                state = str(_row_value(row, "STATE") or "").upper()
                if state == "SUCCEEDED":
                    return
                if state in TERMINAL_TASK_FAILURES:
                    raise CertificationFailure(
                        f"task {task_name} ended {state}: {_row_value(row, 'ERROR_MESSAGE')}"
                    )
            time.sleep(2)
        raise CertificationFailure(f"timed out waiting for {task_name} task run from {scheduled_from}")

    def _certify_append(self) -> None:
        dataset = "append_events"
        spec = self._dataset_spec(dataset)
        names = self._names(dataset, "append")
        self._insert_rows(dataset, spec["events"]["initial"])
        self._call_apply(names)
        self._insert_rows(dataset, spec["events"]["duplicate"])
        self._call_apply(names)
        self._assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation}", 1)

        self.client.execute_sql(f"ALTER TASK {names.task} RESUME;")
        self._insert_rows(dataset, spec["events"]["task_trigger"])
        self._poll_task(names.task.split(".", 1)[1], "TRIGGER")
        self.client.execute_sql(f"ALTER TASK {names.task} SUSPEND;")
        self._assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation}", 2)
        self.report.pass_check("append")
        self.report.pass_check("triggered_task")

    def _certify_scd1(self) -> None:
        dataset = "scd1_customer"
        spec = self._dataset_spec(dataset)
        names = self._names(dataset, "scd1")
        for step, expected in (
            ("initial", "A"),
            ("update", "B"),
            ("duplicate", "B"),
            ("late_arrival", "B"),
        ):
            self._insert_rows(dataset, spec["events"][step])
            self._call_apply(names)
            self._assert_scalar(
                f"SELECT VALUE AS ACTUAL FROM {names.physical_relation} WHERE ID = '1'",
                expected,
            )
        self._insert_rows(dataset, spec["events"]["delete"])
        self._call_apply(names)
        self._assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation} WHERE ID = '1'", 0)
        self._insert_rows(dataset, spec["events"]["reinsert"])
        self._call_apply(names)
        self._insert_rows(dataset, spec["events"]["out_of_order"])
        self._call_apply(names)
        self._assert_scalar(
            f"SELECT VALUE AS ACTUAL FROM {names.physical_relation} WHERE ID = '1'",
            "C",
        )
        self.report.pass_check("scd1")

    def _certify_scd2(self) -> None:
        dataset = "scd2_customer"
        spec = self._dataset_spec(dataset)
        names = self._names(dataset, "scd2")
        for step in ("initial", "update", "later_update", "late_arrival", "delete", "reinsert"):
            self._insert_rows(dataset, spec["events"][step])
            self._call_apply(names)
        history = names.history_relation
        assert history
        self._assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {history}", 5)
        self._assert_scalar(
            "SELECT COUNT(*) AS ACTUAL FROM " + history + " WHERE "
            "(VALUE='A' AND VALID_FROM=TO_TIMESTAMP_NTZ('2026-01-03 10:00:00') AND VALID_TO=TO_TIMESTAMP_NTZ('2026-01-03 11:00:00')) OR "
            "(VALUE='B' AND VALID_FROM=TO_TIMESTAMP_NTZ('2026-01-03 11:00:00') AND VALID_TO=TO_TIMESTAMP_NTZ('2026-01-03 12:00:00')) OR "
            "(VALUE='C' AND VALID_FROM=TO_TIMESTAMP_NTZ('2026-01-03 12:00:00') AND VALID_TO=TO_TIMESTAMP_NTZ('2026-01-03 13:00:00')) OR "
            "(VALUE='D' AND VALID_FROM=TO_TIMESTAMP_NTZ('2026-01-03 13:00:00') AND VALID_TO=TO_TIMESTAMP_NTZ('2026-01-03 14:00:00')) OR "
            "(VALUE='E' AND VALID_FROM=TO_TIMESTAMP_NTZ('2026-01-03 15:00:00') AND VALID_TO IS NULL AND IS_ACTIVE)",
            5,
        )
        self._assert_scalar(f"SELECT VALUE AS ACTUAL FROM {names.current_relation} WHERE ID='1'", "E")
        self.client.execute_sql(f"CALL {names.replay_procedure}(NULL, NULL);")
        self._assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {history}", 5)
        self._assert_scalar(f"SELECT VALUE AS ACTUAL FROM {names.current_relation} WHERE ID='1'", "E")
        self.report.pass_check("scd2")
        self.report.pass_check("late_arriving_history")
        self.report.pass_check("replay")

    def _certify_full_refresh(self) -> None:
        dataset = "full_reference"
        spec = self._dataset_spec(dataset)
        names = self._names(dataset, "full_refresh")
        self._insert_rows(dataset, spec["snapshots"]["initial"], replace=True)
        self.client.execute_sql(f"EXECUTE TASK {names.task};")
        self._poll_task(names.task.split(".", 1)[1], "EXECUTE_TASK")
        self._assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation}", 2)

        self._insert_rows(dataset, spec["snapshots"]["replacement"], replace=True)
        self._call_apply(names)
        self._assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation}", 2)
        self._assert_scalar(
            f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation} WHERE ID IN ('2','3')",
            2,
        )
        self._assert_scalar(
            f"SELECT VALUE AS ACTUAL FROM {names.physical_relation} WHERE ID='2'",
            "blue2",
        )
        self.report.pass_check("full_refresh")
        self.report.pass_check("manual_task")

    def _certify_quality_evidence(self) -> None:
        assert self.project is not None
        for dataset_id, spec in self.project.fixture["datasets"].items():
            names = self._names(str(dataset_id), str(spec["pattern"]))
            self._call_validate(names)
        self._assert_scalar(
            "SELECT COUNT_IF(STATUS <> 'PASS') AS ACTUAL FROM CONTROL.DQ_RESULT "
            "WHERE VERSION='v1' AND DATASET_ID LIKE 'cert_source.%'",
            0,
        )
        self.report.pass_check("dq_evidence")

    def _certify_candidate_release(self) -> None:
        assert self.project is not None
        self.project = add_scd2_candidate(self.project, "v2")
        output = self._run_migrate(self.project.project_git_sha)
        if "APPLY silver_processing/cert_source/scd2_customer/versions/v2/001_objects.sql" not in output:
            raise CertificationFailure("candidate migration deployment did not apply v2 objects")

        v1 = self._names("scd2_customer", "scd2", "v1")
        v2 = self._names("scd2_customer", "scd2", "v2")
        self.client.execute_sql(f"CALL {v2.replay_procedure}(NULL, NULL);")
        self._call_validate(v2)
        compare = self.project.root / "silver_processing" / "cert_source" / "scd2_customer" / "versions" / "v2" / "025_compare.sql"
        self.client.execute_file(compare)
        self._assert_scalar(
            "SELECT COUNT_IF(STATUS='FAIL') AS ACTUAL FROM CONTROL.DQ_RESULT "
            "WHERE DATASET_ID='cert_source.scd2_customer' AND VERSION='v2'",
            0,
        )
        self._assert_scalar(
            "SELECT IFF(COUNT(*) > 0, 1, 0) AS ACTUAL FROM CONTROL.VERSION_VALIDATION "
            "WHERE DATASET_ID='cert_source.scd2_customer' AND CANDIDATE_VERSION='v2'",
            1,
        )

        assert v2.history_relation and v1.published_current
        self.client.execute_sql(
            f"UPDATE {v2.history_relation} SET VALUE='candidate_release_marker' WHERE ID='1' AND IS_ACTIVE=TRUE;"
        )
        self.client.execute_sql(f"GRANT SELECT ON VIEW {v1.published_current} TO ROLE {CERT_ROLE};")
        self._assert_scalar(
            "SELECT COUNT(*) AS ACTUAL FROM INFORMATION_SCHEMA.OBJECT_PRIVILEGES "
            f"WHERE OBJECT_SCHEMA='SILVER' AND OBJECT_NAME='{v1.published_current.split('.', 1)[1]}' "
            f"AND GRANTEE='{CERT_ROLE}' AND PRIVILEGE_TYPE='SELECT'",
            1,
        )

        release = generate_release_scripts(
            project_root=self.project.root,
            source_id="cert_source",
            dataset_id="scd2_customer",
            from_version="v1",
            to_version="v2",
        )
        self.client.execute_file(release.destination / "activate.sql")
        self._assert_scalar(f"SELECT VALUE AS ACTUAL FROM {v1.published_current} WHERE ID='1'", "candidate_release_marker")
        self._assert_scalar(
            "SELECT COUNT(*) AS ACTUAL FROM INFORMATION_SCHEMA.OBJECT_PRIVILEGES "
            f"WHERE OBJECT_SCHEMA='SILVER' AND OBJECT_NAME='{v1.published_current.split('.', 1)[1]}' "
            f"AND GRANTEE='{CERT_ROLE}' AND PRIVILEGE_TYPE='SELECT'",
            1,
        )
        self.client.execute_file(release.destination / "rollback.sql")
        self._assert_scalar(f"SELECT VALUE AS ACTUAL FROM {v1.published_current} WHERE ID='1'", "E")
        self._assert_scalar(
            "SELECT COUNT(*) AS ACTUAL FROM INFORMATION_SCHEMA.OBJECT_PRIVILEGES "
            f"WHERE OBJECT_SCHEMA='SILVER' AND OBJECT_NAME='{v1.published_current.split('.', 1)[1]}' "
            f"AND GRANTEE='{CERT_ROLE}' AND PRIVILEGE_TYPE='SELECT'",
            1,
        )
        self.report.pass_check("candidate_v2_bootstrap")
        self.report.pass_check("cutover")
        self.report.pass_check("rollback")
        self.report.pass_check("published_view_grants")

    def _certify_checksum_drift(self) -> None:
        assert self.project is not None
        migration = self.project.root / "silver_processing" / "cert_source" / "append_events" / "030_task.sql"
        original = migration.read_text(encoding="utf-8")
        migration.write_text(original + "\n-- intentional certification checksum drift\n", encoding="utf-8")
        try:
            output = self._run_migrate(self.project.project_git_sha, expected_code=2)
            if "checksum changed" not in output.lower():
                raise CertificationFailure(f"checksum drift did not fail for the expected reason: {output}")
        finally:
            migration.write_text(original, encoding="utf-8")
        self.report.pass_check("migration_checksum_drift")

    def _certify_failed_migration(self) -> None:
        assert self.project is not None
        failure_rel = "silver_processing/zz_certification_expected_failure.sql"
        failure_path = self.project.root / failure_rel
        failure_path.write_text("SELECT * FROM ESF_CERTIFICATION_OBJECT_THAT_MUST_NOT_EXIST;\n", encoding="utf-8")
        manifest = self.project.root / "silver_processing" / "deploy_manifest.txt"
        manifest.write_text(manifest.read_text(encoding="utf-8").rstrip() + "\n" + failure_rel + "\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project.root), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(self.project.root), "commit", "-m", "certification expected migration failure"],
            check=True,
            text=True,
            capture_output=True,
        )
        failed_sha = subprocess.check_output(
            ["git", "-C", str(self.project.root), "rev-parse", "HEAD"], text=True
        ).strip()
        self._run_migrate(failed_sha, expected_code=5)
        self._assert_scalar(
            "SELECT STATUS AS ACTUAL FROM CONTROL.DEPLOYMENT_HISTORY "
            f"WHERE MIGRATION_PATH='{failure_rel}' ORDER BY STARTED_AT DESC LIMIT 1",
            "FAILED",
        )
        output = self._run_migrate(failed_sha, expected_code=2)
        if "unresolved failed" not in output.lower():
            raise CertificationFailure(f"failed migration was not blocked on retry: {output}")
        self.report.pass_check("migration_failure_block")

    def run(self) -> CertificationReport:
        try:
            identity = self._query_one(
                "SELECT CURRENT_DATABASE() AS DB, CURRENT_ROLE() AS ROLE, CURRENT_WAREHOUSE() AS WH, "
                "CURRENT_VERSION() AS SNOWFLAKE_VERSION"
            )
            if str(_row_value(identity, "DB")) != CERT_DATABASE:
                raise CertificationFailure("Snowflake current database does not match certification database")
            if str(_row_value(identity, "ROLE")) != CERT_ROLE:
                raise CertificationFailure("Snowflake current role does not match certification role")
            self.report.snowflake_version = str(_row_value(identity, "SNOWFLAKE_VERSION") or "UNKNOWN")

            reset_certification_schemas(self.client)
            self.project = build_certification_project(self.workspace_root, self.fixture_path)
            self._create_bronze_tables()

            first = self._run_migrate(self.project.project_git_sha)
            if "Applied: 0" in first:
                raise CertificationFailure("fresh certification deployment unexpectedly applied zero migrations")
            repeat = self._run_migrate(self.project.project_git_sha)
            if "Applied: 0" not in repeat:
                raise CertificationFailure(f"repeat migration deployment was not a zero-apply run: {repeat}")
            self.report.pass_check("apply_once_first_deploy")
            self.report.pass_check("apply_once_repeat_deploy")

            self._certify_append()
            self._certify_scd1()
            self._certify_scd2()
            self._certify_full_refresh()
            self._certify_quality_evidence()
            self._certify_candidate_release()
            self._certify_checksum_drift()
            self._certify_failed_migration()
            self.report.complete()
            return self.report
        except BaseException as exc:
            self.report.fail(exc)
            raise
        finally:
            self.report.write(self.output_dir)
