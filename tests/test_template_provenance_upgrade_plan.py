from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

import yaml

from enterprise_snowflake_framework.cli import _build_parser
from enterprise_snowflake_framework.init_project import initialize_project
from enterprise_snowflake_framework.scaffold import scaffold_pipeline, scaffold_preview
from enterprise_snowflake_framework.source_management import add_source
from enterprise_snowflake_framework.template_provenance import (
    FRAMEWORK_VERSION,
    TemplateAdvisory,
    build_upgrade_plan,
)
from enterprise_snowflake_framework.validation import validate_project_tree
from enterprise_snowflake_framework.versioning import scaffold_version


RAW_TEMPLATE = """schema_version: 2
contract:
  source_system: fleet_mssql
  entity: customer
  grain: one row per source change
  business_key:
    - id
  source_timestamp: source_updated_at
  columns:
    - name: id
      type: VARCHAR
      nullable: false
    - name: name
      type: VARCHAR
      nullable: true
    - name: source_updated_at
      type: TIMESTAMP_NTZ
      nullable: false
    - name: source_sequence
      type: NUMBER
      nullable: false
    - name: source_operation
      type: VARCHAR
      nullable: false
    - name: ingested_at
      type: TIMESTAMP_LTZ
      nullable: false
  change_semantics:
    mode: cdc
    operation_column: source_operation
    sequence_column: source_sequence
    delete_semantics: tombstone
    delete_values: [D]
  capture_fidelity: full_change
  ordering_columns:
    - source_updated_at
    - source_sequence
  idempotency_key:
    - id
    - source_sequence
  breaking_change_policy: versioned_contract
"""


class TemplateProvenanceUpgradePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "enterprise-snowflake-transport-analytics"
        initialize_project(self.root)
        add_source(self.root, "fleet_mssql")
        raw = self.root / "contracts" / "raw" / "fleet_mssql" / "customer.yml"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(RAW_TEMPLATE, encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "source": {"id": "fleet_mssql", "owner": "transport"},
            "datasets": {
                "customer": {
                    "pattern": "scd2",
                    "raw_contract": "contracts/raw/fleet_mssql/customer.yml",
                }
            },
        }
        (self.root / "config" / "sources" / "fleet_mssql.yml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )

    def _scaffold(self) -> Path:
        return scaffold_pipeline(
            project_root=self.root,
            source_id="fleet_mssql",
            pattern="scd2",
            dataset_id="customer",
        ).destination

    def _snapshot(self) -> dict[str, bytes]:
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }

    def test_new_v1_and_candidate_versions_declare_deterministic_provenance(self) -> None:
        preview_a = scaffold_preview(
            project_root=self.root, source_id="fleet_mssql", dataset_id="customer"
        )
        preview_b = scaffold_preview(
            project_root=self.root, source_id="fleet_mssql", dataset_id="customer"
        )
        self.assertEqual(preview_a.rendered["version.yml"], preview_b.rendered["version.yml"])

        v1 = self._scaffold()
        v1_doc = yaml.safe_load((v1 / "version.yml").read_text(encoding="utf-8"))
        provenance = v1_doc["version"]["provenance"]
        self.assertEqual(FRAMEWORK_VERSION, provenance["framework_version"])
        self.assertEqual("scd2_stream_task", provenance["template_id"])
        self.assertEqual(1, provenance["template_revision"])
        self.assertRegex(provenance["template_digest"], r"^sha256:[0-9a-f]{64}$")

        v2 = scaffold_version(
            project_root=self.root,
            source_id="fleet_mssql",
            dataset_id="customer",
            version="v2",
        ).destination
        v2_doc = yaml.safe_load((v2 / "version.yml").read_text(encoding="utf-8"))
        self.assertEqual(provenance, v2_doc["version"]["provenance"])
        self.assertFalse(validate_project_tree(self.root))

    def test_legacy_version_without_provenance_is_unknown_and_never_inferred_from_sql(self) -> None:
        v1 = self._scaffold()
        version_file = v1 / "version.yml"
        document = yaml.safe_load(version_file.read_text(encoding="utf-8"))
        del document["version"]["provenance"]
        version_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        (v1 / "010_apply.sql").write_text(
            "-- misleading text: template_id=scd2_stream_task template_revision=1\n",
            encoding="utf-8",
        )

        before = self._snapshot()
        plan = build_upgrade_plan(self.root)
        after = self._snapshot()

        self.assertEqual(before, after)
        self.assertEqual(1, len(plan.entries))
        self.assertEqual("UNKNOWN", plan.entries[0].status)
        self.assertIsNone(plan.entries[0].provenance)
        self.assertIn("not inferred from SQL", plan.entries[0].reason)
        self.assertIn("No files changed.", plan.render())

    def test_digest_mismatch_is_unverified_not_guessed(self) -> None:
        v1 = self._scaffold()
        version_file = v1 / "version.yml"
        document = yaml.safe_load(version_file.read_text(encoding="utf-8"))
        document["version"]["provenance"]["template_digest"] = "sha256:" + ("0" * 64)
        version_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

        entry = build_upgrade_plan(self.root).entries[0]
        self.assertEqual("UNVERIFIED", entry.status)
        self.assertIn("does not match", entry.reason)

    def test_real_advisory_contract_can_match_a_declared_revision_without_writing(self) -> None:
        self._scaffold()
        advisory = TemplateAdvisory(
            advisory_id="ESF-TEST-001",
            severity="HIGH",
            template_id="scd2_stream_task",
            affected_max_revision=1,
            issue="fixture issue for advisory matching",
            recommendation="create a new candidate with the current template and compare evidence",
        )
        before = self._snapshot()
        plan = build_upgrade_plan(self.root, advisories=(advisory,))
        after = self._snapshot()

        self.assertEqual(before, after)
        self.assertEqual("ADVISORY", plan.entries[0].status)
        self.assertEqual((advisory,), plan.entries[0].advisories)
        rendered = plan.render()
        self.assertIn("ADVISORY ESF-TEST-001", rendered)
        self.assertIn("severity: HIGH", rendered)
        self.assertIn("No files changed.", rendered)

    def test_upgrade_plan_is_a_first_class_esf_subcommand(self) -> None:
        args = _build_parser().parse_args(["upgrade-plan", "--project-root", str(self.root)])
        self.assertEqual("upgrade-plan", args.command)
        self.assertEqual(self.root, args.project_root)

    def test_framework_release_identity_matches_pyproject(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((repository_root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["version"], FRAMEWORK_VERSION)


if __name__ == "__main__":
    unittest.main()
