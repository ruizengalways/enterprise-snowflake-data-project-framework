from pathlib import Path

path = Path('src/enterprise_snowflake_framework/pipeline_replay.py')
text = path.read_text(encoding='utf-8')
old = '''    changes = contract.get("change_semantics", {})
    if changes.get("delete_semantics") == "tombstone" and changes.get("operation_column"):
        op = str(changes["operation_column"]).upper()
        values = ", ".join(
            "'" + str(value).replace("'", "''").upper() + "'"
            for value in changes.get("delete_values", [])
        )
        replay_action = f"IFF(UPPER(COALESCE(TO_VARCHAR(B.{op}), '')) IN ({values}), 'DELETE', 'INSERT')"
    else:
        replay_action = "'INSERT'"
'''
new = '''    # Replay reads retained Bronze evidence as rows. A source tombstone remains a row
    # whose delete meaning is carried by the reviewed operation column; it is not a
    # reconstructed Snowflake physical DELETE event.
    replay_action = "'INSERT'"
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one SCD2 replay-action block, found {text.count(old)}')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
