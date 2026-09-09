from __future__ import annotations

from typing import Any

from .pipeline_model import (
    PipelineNames, _column_defs, _csv, _delete_expression, _join, _typed_defs,
    column_names, ordered_columns, tracked_columns,
)


def _procedure_header(names: PipelineNames) -> str:
    return f"""CREATE OR REPLACE PROCEDURE {names.apply_procedure}()\nRETURNS OBJECT\nLANGUAGE SQL\nEXECUTE AS OWNER\nAS\n$$\nDECLARE\n    V_RUN_ID VARCHAR DEFAULT UUID_STRING();\n    V_ROWS_READ NUMBER DEFAULT 0;\n    V_ROWS_INSERTED NUMBER DEFAULT 0;\n    V_ROWS_UPDATED NUMBER DEFAULT 0;\n    V_ROWS_DELETED NUMBER DEFAULT 0;\n    V_DATA_MAX_AT TIMESTAMP_LTZ;\nBEGIN\n"""


def _running_log(names: PipelineNames) -> str:
    return f"""    INSERT INTO CONTROL.PIPELINE_RUN (\n        RUN_ID, DATASET_ID, VERSION, STATUS, STARTED_AT, TASK_NAME, WAREHOUSE_NAME\n    )\n    SELECT\n        :V_RUN_ID, '{names.dataset_key}', '{names.version}', 'RUNNING',\n        CURRENT_TIMESTAMP(), '{names.task}', CURRENT_WAREHOUSE();\n"""


def _success_log() -> str:
    return """    UPDATE CONTROL.PIPELINE_RUN\n    SET STATUS = 'SUCCESS',\n        COMPLETED_AT = CURRENT_TIMESTAMP(),\n        ROWS_READ = :V_ROWS_READ,\n        ROWS_INSERTED = :V_ROWS_INSERTED,\n        ROWS_UPDATED = :V_ROWS_UPDATED,\n        ROWS_DELETED = :V_ROWS_DELETED,\n        BRONZE_DATA_MAX_AT = :V_DATA_MAX_AT,\n        SILVER_DATA_MAX_AT = :V_DATA_MAX_AT,\n        SILVER_PUBLISHED_AT = CURRENT_TIMESTAMP(),\n        QUERY_ID = LAST_QUERY_ID()\n    WHERE RUN_ID = :V_RUN_ID;\n"""


def _result_and_end() -> str:
    return """    RETURN OBJECT_CONSTRUCT(\n        'run_id', V_RUN_ID,\n        'rows_read', V_ROWS_READ,\n        'rows_inserted', V_ROWS_INSERTED,\n        'rows_updated', V_ROWS_UPDATED,\n        'rows_deleted', V_ROWS_DELETED\n    );\nEND;\n$$;\n"""


def _transaction_failure_block() -> str:
    return """        COMMIT;\n    EXCEPTION\n        WHEN OTHER THEN\n            ROLLBACK;\n            UPDATE CONTROL.PIPELINE_RUN\n            SET STATUS = 'FAILED',\n                COMPLETED_AT = CURRENT_TIMESTAMP(),\n                ERROR_CODE = TO_VARCHAR(SQLCODE),\n                ERROR_MESSAGE = SQLERRM\n            WHERE RUN_ID = :V_RUN_ID;\n            RAISE;\n    END;\n\n"""


def freshness_column(contract: dict[str, Any]) -> str | None:
    if contract.get("source_timestamp"):
        return str(contract["source_timestamp"]).upper()
    names = column_names(contract)
    return "INGESTED_AT" if "INGESTED_AT" in names else None


def render_apply_sql(pattern: str, names: PipelineNames, contract: dict[str, Any]) -> str:
    columns = column_names(contract)
    business_key = [str(value).upper() for value in contract.get("business_key", [])]
    idempotency = [str(value).upper() for value in contract.get("idempotency_key", [])]
    ordering = ordered_columns(contract)
    source_timestamp = str(contract.get("source_timestamp", "")).upper() or None
    tracked = tracked_columns(contract)
    freshness = freshness_column(contract) or "CURRENT_TIMESTAMP()"

    if pattern == "custom":
        return (
            f"-- {names.dataset_key} {names.version}: custom apply logic.\n"
            "-- Keep production transformation explicit in this file.\n"
        )

    header = _procedure_header(names)
    running = _running_log(names)
    success = _success_log()
    end = _result_and_end()
    tx_failure = _transaction_failure_block()

    if pattern == "append":
        assert names.stream and names.physical_relation
        new_defs = _column_defs(contract)
        dedup = _join("T", "N", idempotency)
        return f"""{header}    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_NEW_EVENTS (\n{new_defs}\n    );\n\n{running}    BEGIN\n        BEGIN TRANSACTION;\n\n        INSERT INTO ESF_NEW_EVENTS ({_csv(columns)})\n        SELECT {_csv(columns)}\n        FROM {names.stream}\n        WHERE METADATA$ACTION = 'INSERT';\n\n        V_ROWS_READ := (SELECT COUNT(*) FROM ESF_NEW_EVENTS);\n        V_DATA_MAX_AT := (SELECT MAX({freshness}) FROM ESF_NEW_EVENTS);\n\n        INSERT INTO {names.physical_relation} ({_csv(columns)}, ESF_LOADED_AT)\n        SELECT {_csv(columns, 'N')}, CURRENT_TIMESTAMP()\n        FROM ESF_NEW_EVENTS N\n        WHERE NOT EXISTS (\n            SELECT 1\n            FROM {names.physical_relation} T\n            WHERE {dedup}\n        );\n\n        V_ROWS_INSERTED := SQLROWCOUNT;\n{tx_failure}{success}{end}"""

    if pattern == "full_refresh":
        assert names.physical_relation
        return f"""{header}{running}    BEGIN\n        BEGIN TRANSACTION;\n\n        V_ROWS_READ := (SELECT COUNT(*) FROM {names.bronze_relation});\n        V_DATA_MAX_AT := (SELECT MAX({freshness}) FROM {names.bronze_relation});\n\n        INSERT OVERWRITE INTO {names.physical_relation} ({_csv(columns)}, ESF_LOADED_AT)\n        SELECT {_csv(columns)}, CURRENT_TIMESTAMP()\n        FROM {names.bronze_relation};\n\n        V_ROWS_INSERTED := SQLROWCOUNT;\n{tx_failure}{success}{end}"""

    if pattern == "scd1":
        assert names.stream and names.physical_relation
        new_defs = _column_defs(contract)
        order_desc = ", ".join(f"{name} DESC" for name in ordering) or ", ".join(f"{name} DESC" for name in business_key)
        delete_expr = _delete_expression(contract, "N")
        join = _join("T", "N", business_key)
        updates = [name for name in columns if name not in business_key]
        update_set = ",\n            ".join(f"T.{name} = N.{name}" for name in updates)
        return f"""{header}    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_NEW_EVENTS (\n{new_defs},\n        ESF_STREAM_ACTION VARCHAR NOT NULL,\n        ESF_STREAM_ISUPDATE BOOLEAN NOT NULL\n    );\n\n{running}    BEGIN\n        BEGIN TRANSACTION;\n\n        INSERT INTO ESF_NEW_EVENTS ({_csv(columns)}, ESF_STREAM_ACTION, ESF_STREAM_ISUPDATE)\n        SELECT\n            {_csv(columns)},\n            METADATA$ACTION,\n            METADATA$ISUPDATE\n        FROM {names.stream}\n        WHERE NOT (METADATA$ACTION = 'DELETE' AND METADATA$ISUPDATE);\n\n        V_ROWS_READ := (SELECT COUNT(*) FROM ESF_NEW_EVENTS);\n        V_DATA_MAX_AT := (SELECT MAX({freshness}) FROM ESF_NEW_EVENTS);\n\n        MERGE INTO {names.physical_relation} T\n        USING (\n            SELECT *\n            FROM ESF_NEW_EVENTS\n            QUALIFY ROW_NUMBER() OVER (\n                PARTITION BY {_csv(business_key)}\n                ORDER BY {order_desc}\n            ) = 1\n        ) N\n        ON {join}\n        WHEN MATCHED AND {delete_expr} THEN DELETE\n        WHEN MATCHED THEN UPDATE SET\n            {update_set},\n            T.ESF_LOADED_AT = CURRENT_TIMESTAMP()\n        WHEN NOT MATCHED AND NOT {delete_expr} THEN INSERT (\n            {_csv(columns)}, ESF_LOADED_AT\n        ) VALUES (\n            {_csv(columns, 'N')}, CURRENT_TIMESTAMP()\n        );\n\n        V_ROWS_UPDATED := SQLROWCOUNT;\n{tx_failure}{success}{end}"""

    if pattern == "scd2":
        assert names.stream and names.events_relation and names.history_relation
        if not source_timestamp or not ordering or not tracked:
            raise ValueError("scd2 SQL rendering requires source_timestamp, ordering columns and tracked columns")
        new_defs = _column_defs(contract)
        key_defs = _typed_defs(contract, business_key)
        dedup = _join("E", "N", idempotency) + " AND E.ESF_STREAM_ACTION = N.ESF_STREAM_ACTION"
        affected_events = _join("E", "K", business_key)
        affected_history = _join("H", "K", business_key)
        state_hash = "TO_VARCHAR(HASH(" + _csv(tracked, "E") + "))"
        delete_expr = _delete_expression(contract, "E")
        order_e = ", ".join(f"E.{name}" for name in ordering)
        order_plain = ", ".join(ordering)
        return f"""{header}    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_NEW_EVENTS (\n{new_defs},\n        ESF_STREAM_ACTION VARCHAR NOT NULL,\n        ESF_STREAM_ISUPDATE BOOLEAN NOT NULL\n    );\n\n    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_AFFECTED_KEYS (\n{key_defs}\n    );\n\n{running}    BEGIN\n        BEGIN TRANSACTION;\n\n        INSERT INTO ESF_NEW_EVENTS ({_csv(columns)}, ESF_STREAM_ACTION, ESF_STREAM_ISUPDATE)\n        SELECT\n            {_csv(columns)},\n            METADATA$ACTION,\n            METADATA$ISUPDATE\n        FROM {names.stream}\n        WHERE NOT (METADATA$ACTION = 'DELETE' AND METADATA$ISUPDATE);\n\n        V_ROWS_READ := (SELECT COUNT(*) FROM ESF_NEW_EVENTS);\n        V_DATA_MAX_AT := (SELECT MAX({freshness}) FROM ESF_NEW_EVENTS);\n\n        INSERT INTO {names.events_relation} (\n            {_csv(columns)}, ESF_STREAM_ACTION, ESF_STREAM_ISUPDATE, ESF_EVENT_HASH, ESF_CAPTURED_AT\n        )\n        SELECT\n            {_csv(columns, 'N')},\n            N.ESF_STREAM_ACTION,\n            N.ESF_STREAM_ISUPDATE,\n            TO_VARCHAR(HASH({_csv(columns, 'N')}, N.ESF_STREAM_ACTION)),\n            CURRENT_TIMESTAMP()\n        FROM ESF_NEW_EVENTS N\n        WHERE NOT EXISTS (\n            SELECT 1\n            FROM {names.events_relation} E\n            WHERE {dedup}\n        );\n\n        V_ROWS_INSERTED := SQLROWCOUNT;\n\n        INSERT INTO ESF_AFFECTED_KEYS ({_csv(business_key)})\n        SELECT DISTINCT {_csv(business_key)}\n        FROM ESF_NEW_EVENTS;\n\n        DELETE FROM {names.history_relation} H\n        USING ESF_AFFECTED_KEYS K\n        WHERE {affected_history};\n\n        INSERT INTO {names.history_relation} (\n            {_csv(columns)}, VALID_FROM, VALID_TO, IS_ACTIVE, ESF_VERSION_HASH, ESF_BUILT_AT\n        )\n        WITH ORDERED_EVENTS AS (\n            SELECT\n                E.*,\n                {state_hash} AS ESF_STATE_HASH,\n                {delete_expr} AS ESF_IS_DELETE,\n                LAG({state_hash}) OVER (\n                    PARTITION BY {_csv(business_key, 'E')}\n                    ORDER BY {order_e}\n                ) AS ESF_PREV_STATE_HASH,\n                LAG({delete_expr}) OVER (\n                    PARTITION BY {_csv(business_key, 'E')}\n                    ORDER BY {order_e}\n                ) AS ESF_PREV_IS_DELETE\n            FROM {names.events_relation} E\n            JOIN ESF_AFFECTED_KEYS K\n              ON {affected_events}\n        ),\n        BOUNDARY_EVENTS AS (\n            SELECT\n                *,\n                IFF(\n                    ESF_IS_DELETE\n                    OR ESF_PREV_STATE_HASH IS NULL\n                    OR COALESCE(ESF_PREV_IS_DELETE, FALSE)\n                    OR ESF_STATE_HASH <> ESF_PREV_STATE_HASH,\n                    TRUE,\n                    FALSE\n                ) AS ESF_IS_BOUNDARY\n            FROM ORDERED_EVENTS\n        ),\n        VERSION_BOUNDARIES AS (\n            SELECT\n                *,\n                LEAD({source_timestamp}) OVER (\n                    PARTITION BY {_csv(business_key)}\n                    ORDER BY {order_plain}\n                ) AS ESF_NEXT_BOUNDARY_AT\n            FROM BOUNDARY_EVENTS\n            WHERE ESF_IS_BOUNDARY\n        )\n        SELECT\n            {_csv(columns)},\n            {source_timestamp},\n            ESF_NEXT_BOUNDARY_AT,\n            ESF_NEXT_BOUNDARY_AT IS NULL,\n            ESF_STATE_HASH,\n            CURRENT_TIMESTAMP()\n        FROM VERSION_BOUNDARIES\n        WHERE NOT ESF_IS_DELETE;\n\n        V_ROWS_UPDATED := SQLROWCOUNT;\n{tx_failure}{success}{end}"""

    raise ValueError(f"unsupported pattern: {pattern}")
