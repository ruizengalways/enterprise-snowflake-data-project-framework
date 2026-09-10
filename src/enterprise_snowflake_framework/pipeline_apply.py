from __future__ import annotations

from typing import Any

from .pipeline_idempotency import (
    IDEMPOTENCY_DECLARATIONS,
    render_deduped_relation,
    render_idempotency_conflict_guard,
)
from .pipeline_model import (
    PipelineNames, _column_defs, _csv, _delete_expression, _join, _typed_defs,
    column_names, ordered_columns, tracked_columns,
)


METRICS_CONTRACT_VERSION = 1


def _procedure_header(names: PipelineNames, *, extra_declarations: str = "") -> str:
    if not names.apply_procedure:
        raise ValueError(f"{names.execution_model} implementation has no apply procedure")
    return f"""-- Requires CONTROL migration 110_pipeline_execution_metrics.sql.
-- Canonical metric rule: ROWS_AFFECTED is SQLROWCOUNT for DML_QUERY_ID's primary Silver DML.
CREATE PROCEDURE {names.apply_procedure}()
RETURNS OBJECT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    V_RUN_ID VARCHAR DEFAULT UUID_STRING();
    V_ROWS_READ NUMBER DEFAULT 0;
    V_ROWS_AFFECTED NUMBER DEFAULT 0;
    V_AFFECTED_BUSINESS_KEYS NUMBER DEFAULT 0;
    V_DML_QUERY_ID VARCHAR;
    V_ROWS_INSERTED NUMBER;
    V_ROWS_UPDATED NUMBER;
    V_ROWS_DELETED NUMBER;
    V_DATA_MAX_AT TIMESTAMP_LTZ;
    V_METRICS VARIANT DEFAULT OBJECT_CONSTRUCT();
{extra_declarations}BEGIN
"""


def _running_log(names: PipelineNames) -> str:
    task_value = f"'{names.task}'" if names.task else "NULL"
    return f"""    INSERT INTO CONTROL.PIPELINE_RUN (
        RUN_ID, DATASET_ID, VERSION, STATUS, STARTED_AT, TASK_NAME, WAREHOUSE_NAME,
        METRICS_CONTRACT_VERSION
    )
    SELECT
        :V_RUN_ID, '{names.dataset_key}', '{names.version}', 'RUNNING',
        CURRENT_TIMESTAMP(), {task_value}, CURRENT_WAREHOUSE(), {METRICS_CONTRACT_VERSION};
"""


def _success_log() -> str:
    return f"""    UPDATE CONTROL.PIPELINE_RUN
    SET STATUS = 'SUCCESS',
        COMPLETED_AT = CURRENT_TIMESTAMP(),
        ROWS_READ = :V_ROWS_READ,
        ROWS_AFFECTED = :V_ROWS_AFFECTED,
        AFFECTED_BUSINESS_KEYS = :V_AFFECTED_BUSINESS_KEYS,
        BRONZE_DATA_MAX_AT = :V_DATA_MAX_AT,
        SILVER_DATA_MAX_AT = :V_DATA_MAX_AT,
        SILVER_PUBLISHED_AT = CURRENT_TIMESTAMP(),
        DML_QUERY_ID = :V_DML_QUERY_ID,
        QUERY_ID = :V_DML_QUERY_ID,
        METRICS_CONTRACT_VERSION = {METRICS_CONTRACT_VERSION},
        METRICS = :V_METRICS,
        -- Legacy breakdown fields are only populated when their meaning is unambiguous.
        ROWS_INSERTED = :V_ROWS_INSERTED,
        ROWS_UPDATED = :V_ROWS_UPDATED,
        ROWS_DELETED = :V_ROWS_DELETED
    WHERE RUN_ID = :V_RUN_ID;
"""


def _result_and_end() -> str:
    return """    RETURN OBJECT_CONSTRUCT(
        'run_id', V_RUN_ID,
        'metrics_contract_version', 1,
        'rows_read', V_ROWS_READ,
        'rows_affected', V_ROWS_AFFECTED,
        'affected_business_keys', V_AFFECTED_BUSINESS_KEYS,
        'dml_query_id', V_DML_QUERY_ID,
        'metrics', V_METRICS
    );
END;
$$;
"""


def _transaction_failure_block() -> str:
    return """        COMMIT;
    EXCEPTION
        WHEN OTHER THEN
            ROLLBACK;
            UPDATE CONTROL.PIPELINE_RUN
            SET STATUS = 'FAILED',
                COMPLETED_AT = CURRENT_TIMESTAMP(),
                ERROR_CODE = TO_VARCHAR(SQLCODE),
                ERROR_MESSAGE = SQLERRM
            WHERE RUN_ID = :V_RUN_ID;
            RAISE;
    END;

"""


def _strictly_newer_expression(incoming: str, existing: str, ordering: list[str]) -> str:
    if not ordering:
        return "TRUE"
    clauses: list[str] = []
    equal_prefix: list[str] = []
    for column in ordering:
        comparison = f"{incoming}.{column} > {existing}.{column}"
        if equal_prefix:
            clauses.append("(" + " AND ".join([*equal_prefix, comparison]) + ")")
        else:
            clauses.append(f"({comparison})")
        equal_prefix.append(f"{incoming}.{column} = {existing}.{column}")
    return "(" + " OR ".join(clauses) + ")"


def _distinct_business_keys(relation: str, business_key: list[str]) -> str:
    keys = _csv(business_key)
    return f"(SELECT COUNT(*) FROM (SELECT DISTINCT {keys} FROM {relation}))"


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

    extra_declarations = (
        IDEMPOTENCY_DECLARATIONS if pattern in {"append", "scd2"} else ""
    )
    if pattern == "scd2":
        extra_declarations += """    V_EVENTS_INSERTED NUMBER DEFAULT 0;
    V_EVENTS_INSERT_QUERY_ID VARCHAR;
    V_HISTORY_ROWS_DELETED NUMBER DEFAULT 0;
    V_HISTORY_DELETE_QUERY_ID VARCHAR;
    V_HISTORY_ROWS_REBUILT NUMBER DEFAULT 0;
    V_HISTORY_REBUILD_QUERY_ID VARCHAR;
"""
    header = _procedure_header(names, extra_declarations=extra_declarations)
    running = _running_log(names)
    success = _success_log()
    end = _result_and_end()
    tx_failure = _transaction_failure_block()

    if pattern == "append":
        assert names.stream and names.physical_relation
        new_defs = _column_defs(contract)
        dedup = _join("T", "N", idempotency)
        conflict_guard = render_idempotency_conflict_guard(
            "ESF_NEW_EVENTS",
            identity_columns=idempotency,
            payload_columns=columns,
        )
        deduped_input = render_deduped_relation(
            "ESF_NEW_EVENTS",
            identity_columns=idempotency,
            payload_columns=columns,
            output_alias="N",
        )
        return f"""{header}    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_NEW_EVENTS (
{new_defs}
    );

{running}    BEGIN
        BEGIN TRANSACTION;

        INSERT INTO ESF_NEW_EVENTS ({_csv(columns)})
        SELECT {_csv(columns)}
        FROM {names.stream}
        WHERE METADATA$ACTION = 'INSERT';

        V_ROWS_READ := (SELECT COUNT(*) FROM ESF_NEW_EVENTS);
{conflict_guard}        V_AFFECTED_BUSINESS_KEYS := {_distinct_business_keys('ESF_NEW_EVENTS', business_key)};
        V_DATA_MAX_AT := (SELECT MAX({freshness}) FROM ESF_NEW_EVENTS);

        INSERT INTO {names.physical_relation} ({_csv(columns)}, ESF_LOADED_AT)
        SELECT {_csv(columns, 'N')}, CURRENT_TIMESTAMP()
        FROM {deduped_input}
        WHERE NOT EXISTS (
            SELECT 1
            FROM {names.physical_relation} T
            WHERE {dedup}
        );

        -- Capture DML evidence immediately. Do not call LAST_QUERY_ID() after logging statements.
        V_ROWS_AFFECTED := SQLROWCOUNT;
        V_DML_QUERY_ID := SQLID;
        V_ROWS_INSERTED := V_ROWS_AFFECTED;
        V_ROWS_UPDATED := 0;
        V_ROWS_DELETED := 0;
        V_METRICS := OBJECT_CONSTRUCT(
            'output_rows_inserted', V_ROWS_AFFECTED,
            'primary_dml_query_id', V_DML_QUERY_ID
        );
{tx_failure}{success}{end}"""

    if pattern == "full_refresh":
        assert names.physical_relation
        return f"""{header}{running}    BEGIN
        BEGIN TRANSACTION;

        V_ROWS_READ := (SELECT COUNT(*) FROM {names.bronze_relation});
        V_AFFECTED_BUSINESS_KEYS := {_distinct_business_keys(names.bronze_relation, business_key)};
        V_DATA_MAX_AT := (SELECT MAX({freshness}) FROM {names.bronze_relation});

        INSERT OVERWRITE INTO {names.physical_relation} ({_csv(columns)}, ESF_LOADED_AT)
        SELECT {_csv(columns)}, CURRENT_TIMESTAMP()
        FROM {names.bronze_relation};

        V_ROWS_AFFECTED := SQLROWCOUNT;
        V_DML_QUERY_ID := SQLID;
        V_ROWS_INSERTED := V_ROWS_AFFECTED;
        V_METRICS := OBJECT_CONSTRUCT(
            'snapshot_rows_written', V_ROWS_AFFECTED,
            'primary_dml_query_id', V_DML_QUERY_ID
        );
{tx_failure}{success}{end}"""

    if pattern == "scd1":
        assert names.stream and names.physical_relation
        new_defs = _column_defs(contract)
        order_desc = ", ".join(f"{name} DESC" for name in ordering) or ", ".join(f"{name} DESC" for name in business_key)
        delete_expr = _delete_expression(contract, "N")
        join = _join("T", "N", business_key)
        newer = _strictly_newer_expression("N", "T", ordering)
        updates = [name for name in columns if name not in business_key]
        update_set = ",\n            ".join(f"T.{name} = N.{name}" for name in updates)
        return f"""{header}    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_NEW_EVENTS (
{new_defs},
        ESF_STREAM_ACTION VARCHAR NOT NULL,
        ESF_STREAM_ISUPDATE BOOLEAN NOT NULL
    );

{running}    BEGIN
        BEGIN TRANSACTION;

        INSERT INTO ESF_NEW_EVENTS ({_csv(columns)}, ESF_STREAM_ACTION, ESF_STREAM_ISUPDATE)
        SELECT
            {_csv(columns)},
            METADATA$ACTION,
            METADATA$ISUPDATE
        FROM {names.stream}
        WHERE NOT (METADATA$ACTION = 'DELETE' AND METADATA$ISUPDATE);

        V_ROWS_READ := (SELECT COUNT(*) FROM ESF_NEW_EVENTS);
        V_AFFECTED_BUSINESS_KEYS := {_distinct_business_keys('ESF_NEW_EVENTS', business_key)};
        V_DATA_MAX_AT := (SELECT MAX({freshness}) FROM ESF_NEW_EVENTS);

        -- A late or out-of-order event must not regress the stored current state when
        -- the reviewed RAW contract provides ordering evidence.
        MERGE INTO {names.physical_relation} T
        USING (
            SELECT *
            FROM ESF_NEW_EVENTS
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY {_csv(business_key)}
                ORDER BY {order_desc}
            ) = 1
        ) N
        ON {join}
        WHEN MATCHED AND {newer} AND {delete_expr} THEN DELETE
        WHEN MATCHED AND {newer} THEN UPDATE SET
            {update_set},
            T.ESF_LOADED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED AND NOT {delete_expr} THEN INSERT (
            {_csv(columns)}, ESF_LOADED_AT
        ) VALUES (
            {_csv(columns, 'N')}, CURRENT_TIMESTAMP()
        );

        -- SQLROWCOUNT is total MERGE rows affected, not update-only. Keep legacy
        -- insert/update/delete fields NULL rather than writing a misleading breakdown.
        V_ROWS_AFFECTED := SQLROWCOUNT;
        V_DML_QUERY_ID := SQLID;
        V_METRICS := OBJECT_CONSTRUCT(
            'merge_rows_affected', V_ROWS_AFFECTED,
            'primary_dml_query_id', V_DML_QUERY_ID
        );
{tx_failure}{success}{end}"""

    if pattern == "scd2":
        assert names.stream and names.events_relation and names.history_relation
        if not source_timestamp or not ordering or not tracked:
            raise ValueError("scd2 SQL rendering requires source_timestamp, ordering columns and tracked columns")
        new_defs = _column_defs(contract)
        key_defs = _typed_defs(contract, business_key)
        event_identity = [*idempotency, "ESF_STREAM_ACTION"]
        event_payload = [*columns, "ESF_STREAM_ACTION", "ESF_STREAM_ISUPDATE"]
        dedup = _join("E", "N", idempotency) + " AND E.ESF_STREAM_ACTION = N.ESF_STREAM_ACTION"
        conflict_guard = render_idempotency_conflict_guard(
            "ESF_NEW_EVENTS",
            identity_columns=event_identity,
            payload_columns=event_payload,
        )
        deduped_input = render_deduped_relation(
            "ESF_NEW_EVENTS",
            identity_columns=event_identity,
            payload_columns=event_payload,
            output_alias="N",
        )
        affected_events = _join("E", "K", business_key)
        affected_history = _join("H", "K", business_key)
        state_hash = "TO_VARCHAR(HASH(" + _csv(tracked, "E") + "))"
        delete_expr = _delete_expression(contract, "E")
        order_e = ", ".join(f"E.{name}" for name in ordering)
        order_plain = ", ".join(ordering)
        return f"""{header}    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_NEW_EVENTS (
{new_defs},
        ESF_STREAM_ACTION VARCHAR NOT NULL,
        ESF_STREAM_ISUPDATE BOOLEAN NOT NULL
    );

    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_AFFECTED_KEYS (
{key_defs}
    );

{running}    BEGIN
        BEGIN TRANSACTION;

        INSERT INTO ESF_NEW_EVENTS ({_csv(columns)}, ESF_STREAM_ACTION, ESF_STREAM_ISUPDATE)
        SELECT
            {_csv(columns)},
            METADATA$ACTION,
            METADATA$ISUPDATE
        FROM {names.stream}
        WHERE NOT (METADATA$ACTION = 'DELETE' AND METADATA$ISUPDATE);

        V_ROWS_READ := (SELECT COUNT(*) FROM ESF_NEW_EVENTS);
        V_DATA_MAX_AT := (SELECT MAX({freshness}) FROM ESF_NEW_EVENTS);

{conflict_guard}        INSERT INTO {names.events_relation} (
            {_csv(columns)}, ESF_STREAM_ACTION, ESF_STREAM_ISUPDATE, ESF_EVENT_HASH, ESF_CAPTURED_AT
        )
        SELECT
            {_csv(columns, 'N')},
            N.ESF_STREAM_ACTION,
            N.ESF_STREAM_ISUPDATE,
            TO_VARCHAR(HASH({_csv(columns, 'N')}, N.ESF_STREAM_ACTION)),
            CURRENT_TIMESTAMP()
        FROM {deduped_input}
        WHERE NOT EXISTS (
            SELECT 1
            FROM {names.events_relation} E
            WHERE {dedup}
        );

        V_EVENTS_INSERTED := SQLROWCOUNT;
        V_EVENTS_INSERT_QUERY_ID := SQLID;

        INSERT INTO ESF_AFFECTED_KEYS ({_csv(business_key)})
        SELECT DISTINCT {_csv(business_key)}
        FROM ESF_NEW_EVENTS;

        V_AFFECTED_BUSINESS_KEYS := (SELECT COUNT(*) FROM ESF_AFFECTED_KEYS);

        DELETE FROM {names.history_relation} H
        USING ESF_AFFECTED_KEYS K
        WHERE {affected_history};

        V_HISTORY_ROWS_DELETED := SQLROWCOUNT;
        V_HISTORY_DELETE_QUERY_ID := SQLID;

        INSERT INTO {names.history_relation} (
            {_csv(columns)}, VALID_FROM, VALID_TO, IS_ACTIVE, ESF_VERSION_HASH, ESF_BUILT_AT
        )
        WITH ORDERED_EVENTS AS (
            SELECT
                E.*,
                {state_hash} AS ESF_STATE_HASH,
                {delete_expr} AS ESF_IS_DELETE,
                LAG({state_hash}) OVER (
                    PARTITION BY {_csv(business_key, 'E')}
                    ORDER BY {order_e}
                ) AS ESF_PREV_STATE_HASH,
                LAG({delete_expr}) OVER (
                    PARTITION BY {_csv(business_key, 'E')}
                    ORDER BY {order_e}
                ) AS ESF_PREV_IS_DELETE
            FROM {names.events_relation} E
            JOIN ESF_AFFECTED_KEYS K
              ON {affected_events}
        ),
        BOUNDARY_EVENTS AS (
            SELECT
                *,
                IFF(
                    ESF_IS_DELETE
                    OR ESF_PREV_STATE_HASH IS NULL
                    OR COALESCE(ESF_PREV_IS_DELETE, FALSE)
                    OR ESF_STATE_HASH <> ESF_PREV_STATE_HASH,
                    TRUE,
                    FALSE
                ) AS ESF_IS_BOUNDARY
            FROM ORDERED_EVENTS
        ),
        VERSION_BOUNDARIES AS (
            SELECT
                *,
                LEAD({source_timestamp}) OVER (
                    PARTITION BY {_csv(business_key)}
                    ORDER BY {order_plain}
                ) AS ESF_NEXT_BOUNDARY_AT
            FROM BOUNDARY_EVENTS
            WHERE ESF_IS_BOUNDARY
        )
        SELECT
            {_csv(columns)},
            {source_timestamp},
            ESF_NEXT_BOUNDARY_AT,
            ESF_NEXT_BOUNDARY_AT IS NULL,
            ESF_STATE_HASH,
            CURRENT_TIMESTAMP()
        FROM VERSION_BOUNDARIES
        WHERE NOT ESF_IS_DELETE;

        -- The rebuilt history INSERT is the primary published-Silver DML for the canonical
        -- metric. Event-ledger and history-delete work stay explicit in pattern metrics.
        V_HISTORY_ROWS_REBUILT := SQLROWCOUNT;
        V_HISTORY_REBUILD_QUERY_ID := SQLID;
        V_ROWS_AFFECTED := V_HISTORY_ROWS_REBUILT;
        V_DML_QUERY_ID := V_HISTORY_REBUILD_QUERY_ID;
        V_METRICS := OBJECT_CONSTRUCT(
            'events_inserted', V_EVENTS_INSERTED,
            'event_insert_query_id', V_EVENTS_INSERT_QUERY_ID,
            'history_rows_deleted', V_HISTORY_ROWS_DELETED,
            'history_delete_query_id', V_HISTORY_DELETE_QUERY_ID,
            'history_rows_rebuilt', V_HISTORY_ROWS_REBUILT,
            'history_rebuild_query_id', V_HISTORY_REBUILD_QUERY_ID,
            'primary_dml_query_id', V_DML_QUERY_ID
        );
{tx_failure}{success}{end}"""

    raise ValueError(f"unsupported pattern: {pattern}")