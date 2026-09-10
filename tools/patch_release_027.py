from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise SystemExit(f'expected one marker in {path}, found {text.count(old)}: {old!r}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')


provenance = 'src/enterprise_snowflake_framework/template_provenance.py'
replace_once(provenance, 'FRAMEWORK_VERSION = "0.26.0"', 'FRAMEWORK_VERSION = "0.27.0"')
replace_once(
    provenance,
    '# Revision 3 is limited to append/scd2 Stream+Task templates: incoming apply/replay batches now\n# fail closed on conflicting payloads for one idempotency identity and collapse exact duplicates.\n',
    '# Revision 3 is limited to append/scd2 Stream+Task templates: incoming apply/replay batches now\n# fail closed on conflicting payloads for one idempotency identity and collapse exact duplicates.\n# Revision 4 is SCD2-only: replay of retained Bronze rows preserves synthetic Stream action INSERT;\n# tombstone delete meaning remains in the reviewed source operation column.\n',
)
replace_once(
    provenance,
    '        3: TemplateSpec("scd2_stream_task", 3, _STREAM_TASK_ARTIFACTS),\n    },',
    '        3: TemplateSpec("scd2_stream_task", 3, _STREAM_TASK_ARTIFACTS),\n        4: TemplateSpec("scd2_stream_task", 4, _STREAM_TASK_ARTIFACTS),\n    },',
)

replace_once(
    'tests/test_task_operational_config.py',
    'self.assertEqual(3, version["version"]["provenance"]["template_revision"])',
    'self.assertEqual(4, version["version"]["provenance"]["template_revision"])',
)
