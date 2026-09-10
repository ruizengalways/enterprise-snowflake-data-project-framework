from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one marker in {path}, found {count}: {old!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


for path in (
    "src/enterprise_snowflake_framework/pipeline_apply.py",
    "src/enterprise_snowflake_framework/pipeline_replay.py",
):
    replace_once(
        path,
        "    render_idempotency_conflict_guard,\n)",
        "    render_idempotency_conflict_guard,\n    render_identity_join,\n)",
    )

replace_once(
    "src/enterprise_snowflake_framework/pipeline_apply.py",
    '        dedup = _join("T", "N", idempotency)\n',
    '        dedup = render_identity_join("T", "N", idempotency)\n',
)
replace_once(
    "src/enterprise_snowflake_framework/pipeline_apply.py",
    '        dedup = _join("E", "N", idempotency) + " AND E.ESF_STREAM_ACTION = N.ESF_STREAM_ACTION"\n',
    '        dedup = render_identity_join("E", "N", event_identity)\n',
)
replace_once(
    "src/enterprise_snowflake_framework/pipeline_replay.py",
    '    dedup = _join("T", "N", idempotency)\n',
    '    dedup = render_identity_join("T", "N", idempotency)\n',
)
replace_once(
    "src/enterprise_snowflake_framework/pipeline_replay.py",
    '    dedup = _join("E", "N", idempotency) + " AND E.ESF_STREAM_ACTION = N.ESF_STREAM_ACTION"\n',
    '    dedup = render_identity_join("E", "N", event_identity)\n',
)
