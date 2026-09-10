from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_snowflake_framework.certification_project import (
    add_scd2_candidate,
    build_certification_project,
    load_certification_fixture,
)
from enterprise_snowflake_framework.certification_snowflake import (
    CERT_DATABASE,
    CERT_READER_ROLE,
    CERT_ROLE,
    CERT_USER,
    CERT_WAREHOUSE,
    CertificationFailure,
    CertificationReport,
    _required_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "certification" / "fixtures" / "canonical.yml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "snowflake-certification.yml"


class SnowflakeCertificationContractTests(unittest.TestCase):
    def test_fixture_covers_required_real_snowflake_semantics(self) -> None:
        fixture = load_certification_fixture(FIXTURE)
        patterns = {spec["pattern"] for spec in fixture["datasets"].values()}
        self.assertEqual({"append", "scd1", "scd2", "full_refresh"}, patterns)

        append = fixture["datasets"]["append_events"]["events"]
        self.assertIn("duplicate", append)
        self.assertIn("task_trigger", append)

        scd1 = fixture["datasets"]["scd1_customer"]["events"]
        for step in ("initial", "update", "duplicate", "late_arrival", "delete", "reinsert", "out_of_order"):
            self.assertIn(step, scd1)

        scd2 = fixture["datasets"]["scd2_customer"]["events"]
        for step in (
            "initial",
            "update",
            "later_update",
            "late_arrival",
            "delete",
            "reinsert",
            "candidate_catchup",
        ):
            self.assertIn(step, scd2)

        full_refresh = fixture["datasets"]["full_reference"]["snapshots"]
        self.assertIn("initial", full_refresh)
        self.assertIn("replacement", full_refresh)

    def test_fixture_project_uses_public_scaffolding_and_append_only_candidate_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "enterprise-snowflake-framework-cert-analytics"
            project = build_certification_project(root, FIXTURE)
            self.assertEqual(40, len(project.project_git_sha))
            manifest = (root / "silver_processing" / "deploy_manifest.txt").read_text(encoding="utf-8")
            self.assertIn("silver_processing/cert_source/append_events/001_objects.sql", manifest)
            self.assertIn("silver_processing/cert_source/scd1_customer/030_task.sql", manifest)
            self.assertIn("silver_processing/cert_source/scd2_customer/050_publish.sql", manifest)
            self.assertIn("silver_processing/cert_source/full_reference/050_publish.sql", manifest)
            self.assertNotIn("versions/v2", manifest)

            v1_apply = root / "silver_processing" / "cert_source" / "scd2_customer" / "010_apply.sql"
            v1_bytes = v1_apply.read_bytes()
            candidate = add_scd2_candidate(project)
            manifest_after = (root / "silver_processing" / "deploy_manifest.txt").read_text(encoding="utf-8")
            self.assertNotEqual(project.project_git_sha, candidate.project_git_sha)
            self.assertIn("silver_processing/cert_source/scd2_customer/versions/v2/001_objects.sql", manifest_after)
            self.assertIn("silver_processing/cert_source/scd2_customer/versions/v2/040_register.sql", manifest_after)
            self.assertNotIn("silver_processing/cert_source/scd2_customer/versions/v2/050_publish.sql", manifest_after)
            self.assertEqual(v1_bytes, v1_apply.read_bytes())

    def test_certification_connection_is_hard_scoped_to_dedicated_boundary(self) -> None:
        good = {
            "SNOWFLAKE_DATABASE": CERT_DATABASE,
            "SNOWFLAKE_ROLE": CERT_ROLE,
            "SNOWFLAKE_USER": CERT_USER,
            "SNOWFLAKE_WAREHOUSE": CERT_WAREHOUSE,
        }
        _required_environment(good)
        self.assertEqual("AR_FRAMEWORK_CERT_READER", CERT_READER_ROLE)
        for key in tuple(good):
            bad = dict(good)
            bad[key] = "PROD_TRANSPORT"
            with self.assertRaises(CertificationFailure):
                _required_environment(bad)

    def test_report_never_calls_dynamic_table_certified_before_feature_exists(self) -> None:
        report = CertificationReport(
            framework_git_sha="a" * 40,
            framework_version="0.18.0",
        )
        report.pass_check("append")
        report.complete()
        self.assertEqual("CERTIFIED", report.status)
        self.assertEqual("NOT_APPLICABLE", report.checks["dynamic_table"])

    def test_workflow_never_executes_pull_request_head_with_certification_identity(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("pull_request:", text)
        self.assertIn('github.event.workflow_run.event == \'push\'', text)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", text)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", text)
        self.assertIn("vars.ESF_SNOWFLAKE_CERTIFICATION_ENABLED == 'true'", text)
        self.assertIn("environment: snowflake-certification", text)
        self.assertIn("ref: ${{ steps.trusted.outputs.sha }}", text)
        self.assertNotIn("github.event.pull_request.head.sha", text)
        self.assertIn("if: always() && steps.oidc.outcome == 'success'", text)
        self.assertIn("--cleanup-only", text)
        self.assertIn("actions/upload-artifact@v4.6.2", text)

    def test_runner_contract_covers_migration_task_release_and_grant_certification(self) -> None:
        runtime = (
            REPO_ROOT / "src" / "enterprise_snowflake_framework" / "certification_snowflake.py"
        ).read_text(encoding="utf-8")
        scenarios = (
            REPO_ROOT / "src" / "enterprise_snowflake_framework" / "certification_scenarios.py"
        ).read_text(encoding="utf-8")
        combined = runtime + "\n" + scenarios
        for expected in (
            "apply_once_repeat_deploy",
            "migration_checksum_drift",
            "migration_failure_block",
            "SCHEDULED_FROM",
            '"TRIGGER"',
            '"EXECUTE_TASK"',
            "late_arriving_history",
            "candidate_v2_bootstrap",
            "candidate_v2_catch_up",
            "published_view_grants",
            "cert_reader_role",
            "cutover",
            "rollback",
            "CONTROL.VERSION_VALIDATION",
            "CONTROL.DQ_RESULT",
        ):
            self.assertIn(expected, combined)


if __name__ == "__main__":
    unittest.main()
