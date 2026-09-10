from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .certification_project import add_scd1_dynamic_table_candidate, add_scd2_candidate
from .pipeline_model import build_names
from .versioning import generate_release_scripts

if TYPE_CHECKING:
    from .certification_snowflake import SnowflakeCertificationRuntime


def certify_append(runtime: "SnowflakeCertificationRuntime") -> None:
    dataset = "append_events"
    spec = runtime.dataset_spec(dataset)
    names = runtime.names(dataset, "append")
    runtime.insert_rows(dataset, spec["events"]["initial"])
    runtime.call_apply(names)
    runtime.insert_rows(dataset, spec["events"]["duplicate"])
    runtime.call_apply(names)
    runtime.assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation}", 1)

    runtime.client.execute_sql(f"ALTER TASK {names.task} RESUME;")
    runtime.insert_rows(dataset, spec["events"]["task_trigger"])
    runtime.poll_task(names.task.split(".", 1)[1], "TRIGGER")
    runtime.client.execute_sql(f"ALTER TASK {names.task} SUSPEND;")
    runtime.assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation}", 2)
    runtime.report.pass_check("append")
    runtime.report.pass_check("triggered_task")


def certify_scd1(runtime: "SnowflakeCertificationRuntime") -> None:
    dataset = "scd1_customer"
    spec = runtime.dataset_spec(dataset)
    names = runtime.names(dataset, "scd1")
    for step, expected in (
        ("initial", "A"),
        ("update", "B"),
        ("duplicate", "B"),
        ("late_arrival", "B"),
    ):
        runtime.insert_rows(dataset, spec["events"][step])
        runtime.call_apply(names)
        runtime.assert_scalar(
            f"SELECT VALUE AS ACTUAL FROM {names.physical_relation} WHERE ID = '1'",
            expected,
        )

    runtime.insert_rows(dataset, spec["events"]["delete"])
    runtime.call_apply(names)
    runtime.assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation} WHERE ID = '1'", 0)

    runtime.insert_rows(dataset, spec["events"]["reinsert"])
    runtime.call_apply(names)
    runtime.insert_rows(dataset, spec["events"]["out_of_order"])
    runtime.call_apply(names)
    runtime.assert_scalar(
        f"SELECT VALUE AS ACTUAL FROM {names.physical_relation} WHERE ID = '1'",
        "C",
    )
    runtime.report.pass_check("scd1")


def certify_scd2(runtime: "SnowflakeCertificationRuntime") -> None:
    dataset = "scd2_customer"
    spec = runtime.dataset_spec(dataset)
    names = runtime.names(dataset, "scd2")
    for step in ("initial", "update", "later_update", "late_arrival", "delete", "reinsert"):
        runtime.insert_rows(dataset, spec["events"][step])
        runtime.call_apply(names)

    history = names.history_relation
    assert history
    runtime.assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {history}", 5)
    runtime.assert_scalar(
        "SELECT COUNT(*) AS ACTUAL FROM " + history + " WHERE "
        "(VALUE='A' AND VALID_FROM=TO_TIMESTAMP_NTZ('2026-01-03 10:00:00') AND VALID_TO=TO_TIMESTAMP_NTZ('2026-01-03 11:00:00')) OR "
        "(VALUE='B' AND VALID_FROM=TO_TIMESTAMP_NTZ('2026-01-03 11:00:00') AND VALID_TO=TO_TIMESTAMP_NTZ('2026-01-03 12:00:00')) OR "
        "(VALUE='C' AND VALID_FROM=TO_TIMESTAMP_NTZ('2026-01-03 12:00:00') AND VALID_TO=TO_TIMESTAMP_NTZ('2026-01-03 13:00:00')) OR "
        "(VALUE='D' AND VALID_FROM=TO_TIMESTAMP_NTZ('2026-01-03 13:00:00') AND VALID_TO=TO_TIMESTAMP_NTZ('2026-01-03 14:00:00')) OR "
        "(VALUE='E' AND VALID_FROM=TO_TIMESTAMP_NTZ('2026-01-03 15:00:00') AND VALID_TO IS NULL AND IS_ACTIVE)",
        5,
    )
    runtime.assert_scalar(f"SELECT VALUE AS ACTUAL FROM {names.current_relation} WHERE ID='1'", "E")
    runtime.client.execute_sql(f"CALL {names.replay_procedure}(NULL, NULL);")
    runtime.assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {history}", 5)
    runtime.assert_scalar(f"SELECT VALUE AS ACTUAL FROM {names.current_relation} WHERE ID='1'", "E")
    runtime.report.pass_check("scd2")
    runtime.report.pass_check("late_arriving_history")
    runtime.report.pass_check("replay")


def certify_full_refresh(runtime: "SnowflakeCertificationRuntime") -> None:
    dataset = "full_reference"
    spec = runtime.dataset_spec(dataset)
    names = runtime.names(dataset, "full_refresh")
    runtime.insert_rows(dataset, spec["snapshots"]["initial"], replace=True)
    runtime.client.execute_sql(f"EXECUTE TASK {names.task};")
    runtime.poll_task(names.task.split(".", 1)[1], "EXECUTE_TASK")
    runtime.assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation}", 2)

    runtime.insert_rows(dataset, spec["snapshots"]["replacement"], replace=True)
    runtime.call_apply(names)
    runtime.assert_scalar(f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation}", 2)
    runtime.assert_scalar(
        f"SELECT COUNT(*) AS ACTUAL FROM {names.physical_relation} WHERE ID IN ('2','3')",
        2,
    )
    runtime.assert_scalar(
        f"SELECT VALUE AS ACTUAL FROM {names.physical_relation} WHERE ID='2'",
        "blue2",
    )
    runtime.report.pass_check("full_refresh")
    runtime.report.pass_check("manual_task")


def certify_quality_evidence(runtime: "SnowflakeCertificationRuntime") -> None:
    for dataset_id, spec in runtime.project.fixture["datasets"].items():
        runtime.call_validate(runtime.names(str(dataset_id), str(spec["pattern"])))
    runtime.assert_scalar(
        "SELECT COUNT_IF(STATUS <> 'PASS') AS ACTUAL FROM CONTROL.DQ_RESULT "
        "WHERE VERSION='v1' AND DATASET_ID LIKE 'cert_source.%'",
        0,
    )
    runtime.report.pass_check("dq_evidence")


def certify_candidate_release(runtime: "SnowflakeCertificationRuntime") -> None:
    spec = runtime.dataset_spec("scd2_customer")
    runtime.project = add_scd2_candidate(runtime.project, "v2")
    output = runtime.run_migrate(runtime.project.project_git_sha)
    if "APPLY silver_processing/cert_source/scd2_customer/versions/v2/001_objects.sql" not in output:
        runtime.fail("candidate migration deployment did not apply v2 objects")

    v1 = runtime.names("scd2_customer", "scd2", "v1")
    v2 = runtime.names("scd2_customer", "scd2", "v2")
    runtime.client.execute_sql(f"CALL {v2.replay_procedure}(NULL, NULL);")

    runtime.insert_rows("scd2_customer", spec["events"]["candidate_catchup"])
    runtime.call_apply(v1)
    runtime.call_apply(v2)
    runtime.assert_scalar(f"SELECT VALUE AS ACTUAL FROM {v2.current_relation} WHERE ID='2'", "F")
    runtime.report.pass_check("candidate_v2_catch_up")

    runtime.call_validate(v2)
    compare = runtime.project.root / "silver_processing" / "cert_source" / "scd2_customer" / "versions" / "v2" / "025_compare.sql"
    runtime.client.execute_file(compare)
    runtime.assert_scalar(
        "SELECT COUNT_IF(STATUS='FAIL') AS ACTUAL FROM CONTROL.DQ_RESULT "
        "WHERE DATASET_ID='cert_source.scd2_customer' AND VERSION='v2'",
        0,
    )
    runtime.assert_scalar(
        "SELECT IFF(COUNT(*) > 0, 1, 0) AS ACTUAL FROM CONTROL.VERSION_VALIDATION "
        "WHERE DATASET_ID='cert_source.scd2_customer' AND CANDIDATE_VERSION='v2'",
        1,
    )

    assert v2.history_relation and v1.published_current
    runtime.client.execute_sql(
        f"UPDATE {v2.history_relation} SET VALUE='candidate_release_marker' WHERE ID='1' AND IS_ACTIVE=TRUE;"
    )
    runtime.client.execute_sql(
        f"GRANT SELECT ON VIEW {v1.published_current} TO ROLE {runtime.cert_reader_role};"
    )
    runtime.assert_published_select_grant(v1.published_current)

    release = generate_release_scripts(
        project_root=runtime.project.root,
        source_id="cert_source",
        dataset_id="scd2_customer",
        from_version="v1",
        to_version="v2",
    )
    runtime.client.execute_file(release.destination / "activate.sql")
    runtime.assert_scalar(
        f"SELECT VALUE AS ACTUAL FROM {v1.published_current} WHERE ID='1'",
        "candidate_release_marker",
    )
    runtime.assert_published_select_grant(v1.published_current)

    runtime.client.execute_file(release.destination / "rollback.sql")
    runtime.assert_scalar(f"SELECT VALUE AS ACTUAL FROM {v1.published_current} WHERE ID='1'", "E")
    runtime.assert_published_select_grant(v1.published_current)
    runtime.report.pass_check("candidate_v2_bootstrap")
    runtime.report.pass_check("cutover")
    runtime.report.pass_check("rollback")
    runtime.report.pass_check("published_view_grants")


def certify_dynamic_table(runtime: "SnowflakeCertificationRuntime") -> None:
    dataset = "scd1_customer"
    spec = runtime.dataset_spec(dataset)
    runtime.project = add_scd1_dynamic_table_candidate(runtime.project, "v2")
    output = runtime.run_migrate(runtime.project.project_git_sha)
    migration = "silver_processing/cert_source/scd1_customer/versions/v2/001_dynamic_table.sql"
    if f"APPLY {migration}" not in output:
        runtime.fail("Dynamic Table candidate migration was not applied")

    v1 = runtime.names(dataset, "scd1", "v1")
    v2 = build_names(
        source_id=runtime.project.source_id,
        dataset_id=dataset,
        pattern="scd1",
        entity=dataset,
        version="v2",
        execution_model="dynamic_table",
    )
    assert v1.physical_relation and v1.published_relation and v2.dynamic_table
    runtime.assert_scalar(f"SELECT VALUE AS ACTUAL FROM {v2.dynamic_table} WHERE ID='1'", "C")
    runtime.assert_scalar(
        "SELECT EXECUTION_MODEL AS ACTUAL FROM CONTROL.DATASET_VERSION "
        "WHERE DATASET_ID='cert_source.scd1_customer' AND VERSION='v2'",
        "dynamic_table",
    )
    runtime.assert_scalar(
        "SELECT SILVER_STATUS AS ACTUAL FROM CONTROL.DYNAMIC_TABLE_REFRESH_STATUS_V "
        "WHERE DATASET_ID='cert_source.scd1_customer' AND VERSION='v2'",
        "SUCCESS",
    )

    # A new event after candidate creation must converge under both execution technologies.
    runtime.insert_rows(dataset, spec["events"]["dynamic_catchup"])
    runtime.call_apply(v1)
    runtime.client.execute_sql(f"ALTER DYNAMIC TABLE {v2.dynamic_table} REFRESH;")
    runtime.assert_scalar(f"SELECT VALUE AS ACTUAL FROM {v1.physical_relation} WHERE ID='1'", "DYNAMIC")
    runtime.assert_scalar(f"SELECT VALUE AS ACTUAL FROM {v2.dynamic_table} WHERE ID='1'", "DYNAMIC")
    runtime.assert_scalar(
        "SELECT STATE AS ACTUAL FROM TABLE(INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY("
        f"NAME=>'{v2.dynamic_table}', RESULT_LIMIT=>20)) WHERE REFRESH_TRIGGER='MANUAL' "
        "QUALIFY ROW_NUMBER() OVER (ORDER BY COALESCE(REFRESH_END_TIME, REFRESH_START_TIME, DATA_TIMESTAMP) DESC)=1",
        "SUCCEEDED",
    )

    candidate_root = runtime.project.root / "silver_processing" / "cert_source" / dataset / "versions" / "v2"
    runtime.client.execute_file(candidate_root / "020_validate.sql")
    runtime.client.execute_file(candidate_root / "025_compare.sql")
    runtime.assert_scalar(
        "SELECT COUNT_IF(STATUS='FAIL') AS ACTUAL FROM CONTROL.DQ_RESULT "
        "WHERE DATASET_ID='cert_source.scd1_customer' AND VERSION='v2'",
        0,
    )

    runtime.client.execute_sql(
        f"GRANT SELECT ON VIEW {v1.published_relation} TO ROLE {runtime.cert_reader_role};"
    )
    runtime.assert_published_select_grant(v1.published_relation)
    release = generate_release_scripts(
        project_root=runtime.project.root,
        source_id="cert_source",
        dataset_id=dataset,
        from_version="v1",
        to_version="v2",
    )
    runtime.client.execute_file(release.destination / "activate.sql")
    runtime.assert_scalar(f"SELECT VALUE AS ACTUAL FROM {v1.published_relation} WHERE ID='1'", "DYNAMIC")
    runtime.assert_published_select_grant(v1.published_relation)
    runtime.client.execute_sql("CALL CONTROL.REFRESH_DATASET_HEALTH();")
    runtime.assert_scalar(
        "SELECT ACTIVE_EXECUTION_MODEL AS ACTUAL FROM CONTROL.DATASET_OBSERVABILITY_V "
        "WHERE DATASET_ID='cert_source.scd1_customer'",
        "dynamic_table",
    )
    runtime.assert_scalar(
        "SELECT SILVER_STATUS AS ACTUAL FROM CONTROL.DATASET_OBSERVABILITY_V "
        "WHERE DATASET_ID='cert_source.scd1_customer'",
        "SUCCESS",
    )

    runtime.client.execute_file(release.destination / "rollback.sql")
    runtime.assert_scalar(f"SELECT VALUE AS ACTUAL FROM {v1.published_relation} WHERE ID='1'", "DYNAMIC")
    runtime.assert_published_select_grant(v1.published_relation)
    runtime.report.pass_check("dynamic_table")
    runtime.report.pass_check("cross_execution_model_release")
    runtime.report.pass_check("dynamic_table_observability")


def certify_checksum_drift(runtime: "SnowflakeCertificationRuntime") -> None:
    migration = runtime.project.root / "silver_processing" / "cert_source" / "append_events" / "030_task.sql"
    original = migration.read_text(encoding="utf-8")
    migration.write_text(original + "\n-- intentional certification checksum drift\n", encoding="utf-8")
    try:
        output = runtime.run_migrate(runtime.project.project_git_sha, expected_code=2)
        if "checksum changed" not in output.lower():
            runtime.fail(f"checksum drift did not fail for the expected reason: {output}")
    finally:
        migration.write_text(original, encoding="utf-8")
    runtime.report.pass_check("migration_checksum_drift")


def certify_failed_migration(runtime: "SnowflakeCertificationRuntime") -> None:
    failure_rel = "silver_processing/zz_certification_expected_failure.sql"
    failure_path = runtime.project.root / failure_rel
    failure_path.write_text("SELECT * FROM ESF_CERTIFICATION_OBJECT_THAT_MUST_NOT_EXIST;\n", encoding="utf-8")
    manifest = runtime.project.root / "silver_processing" / "deploy_manifest.txt"
    manifest.write_text(manifest.read_text(encoding="utf-8").rstrip() + "\n" + failure_rel + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(runtime.project.root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(runtime.project.root), "commit", "-m", "certification expected migration failure"],
        check=True,
        text=True,
        capture_output=True,
    )
    failed_sha = subprocess.check_output(
        ["git", "-C", str(runtime.project.root), "rev-parse", "HEAD"], text=True
    ).strip()
    runtime.run_migrate(failed_sha, expected_code=5)
    runtime.assert_scalar(
        "SELECT STATUS AS ACTUAL FROM CONTROL.DEPLOYMENT_HISTORY "
        f"WHERE MIGRATION_PATH='{failure_rel}' ORDER BY STARTED_AT DESC LIMIT 1",
        "FAILED",
    )
    output = runtime.run_migrate(failed_sha, expected_code=2)
    if "unresolved failed" not in output.lower():
        runtime.fail(f"failed migration was not blocked on retry: {output}")
    runtime.report.pass_check("migration_failure_block")


def run_all_scenarios(runtime: "SnowflakeCertificationRuntime") -> None:
    certify_append(runtime)
    certify_scd1(runtime)
    certify_scd2(runtime)
    certify_full_refresh(runtime)
    certify_quality_evidence(runtime)
    certify_candidate_release(runtime)
    certify_dynamic_table(runtime)
    certify_checksum_drift(runtime)
    certify_failed_migration(runtime)
