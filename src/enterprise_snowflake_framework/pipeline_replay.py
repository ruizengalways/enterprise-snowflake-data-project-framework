from __future__ import annotations

from typing import Any

from .pipeline_idempotency import (
    IDEMPOTENCY_DECLARATIONS,
    render_deduped_relation,
    render_idempotency_conflict_guard,
    render_identity_join,
)
from .pipeline_model import (
    PipelineNames,
    _column_defs,
    _csv,
    _delete_expression,
    _join,
    _typed_defs,
    column_names,
    ordered_columns,
    tracked_columns,
)


def _replay_timestamp(contract: dict[str, Any]) -> str | None:
    if contract.get("source_timestamp"):
        return str(contract["source_timestamp"]).upper()
    names = column_names(contract)
    return "INGESTED_AT" if "INGESTED_AT" in names else None


def _range_filter(timestamp_column: str | None, alias: str = "B") -> str:
    if timestamp_column is None:
        return "TRUE"
    return (
        f"(:P_FROM IS NULL OR {alias}.{timestamp_column} >= :P_FROM)\n"
        f"          AND (:P_TO IS NULL OR {alias}.{timestamp_column} < :P_TO)"
    )


def _range_guard(timestamp_column: str | None) -> str:
    if timestamp_column is not None:
        return ""
    return """    IF (P_FROM IS NOT NULL OR P_TO IS NOT NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'status', 'REJECTED',
            'reason', 'RAW contract has no source_timestamp/INGESTED_AT; ranged replay is not supported'
        );
    END IF;

"""


def _repair_start(names: PipelineNames, *, range_values: bool = True) -> str:
    requested_from = ":P_FROM" if range_values else "NULL"
    requested_to = ":P_TO" if range_values else "NULL"
    return f"""    INSERT INTO CONTROL.REPAIR_RUN (
        REPAIR_ID, DATASET_ID, REPAIR_TYPE, REQUESTED_FROM, REQUESTED_TO, STATUS, STARTED_AT, OPERATOR
    )
    SELECT
        :V_REPAIR_ID, '{names.dataset_key}', 'SILVER_REPLAY', {requested_from}, {requested_to},
        'RUNNING', CURRENT_TIMESTAMP(), CURRENT_USER();

"""


def _repair_failure() -> str:
    return """    EXCEPTION
        WHEN OTHER THEN
            ROLLBACK;
            UPDATE CONTROL.REPAIR_RUN
            SET STATUS = 'FAILED', COMPLETED_AT = CURRENT_TIMESTAMP(),
                ERROR_CODE = TO_VARCHAR(SQLCODE), ERROR_MESSAGE = SQLERRM
            WHERE REPAIR_ID = :V_REPAIR_ID;
            RAISE;
    END;

"""


def _repair_success() -> str:
    return """    UPDATE CONTROL.REPAIR_RUN
    SET STATUS = 'SUCCESS', COMPLETED_AT = CURRENT_TIMESTAMP(), ROWS_RECOVERED = :V_ROWS_RECOVERED
    WHERE REPAIR_ID = :V_REPAIR_ID;

    RETURN OBJECT_CONSTRUCT(
        'repair_id', V_REPAIR_ID,
        'rows_read', V_ROWS_READ,
        'rows_recovered', V_ROWS_RECOVERED
    );
END;
$$;
"""


def _tombstone_expression(contract: dict[str, Any], alias: str) -> str:
    changes = contract.get("change_semantics", {})
    if changes.get("delete_semantics") != "tombstone" or not changes.get("operation_column"):
        return "FALSE"
    operation = str(changes["operation_column"]).upper()
    values = ", ".join(
        "'" + str(value).replace("'", "''").upper() + "'"
        for value in changes.get("delete_values", [])
    )
    return (
        f"UPPER(COALESCE(TO_VARCHAR({alias}.{operation}), '')) IN ({values})"
        if values
        else "FALSE"
    )


def _render_append_replay(names: PipelineNames, contract: dict[str, Any]) -> str:
    assert names.physical_relation
    columns = column_names(contract)
    idempotency = [str(value).upper() for value in contract.get("idempotency_key", [])]
    timestamp_column = _replay_timestamp(contract)
    row_filter = _range_filter(timestamp_column)
    new_defs = _column_defs(contract)
    dedup = render_identity_join("T", "N", idempotency)
    conflict_guard = render_idempotency_conflict_guard(
        "ESF_REPLAY_INPUT",
        identity_columns=idempotency,
        payload_columns=columns,
    )
    deduped_input = render_deduped_relation(
        "ESF_REPLAY_INPUT",
        identity_columns=idempotency,
        payload_columns=columns,
        output_alias="N",
    )
    return f"""-- Candidate append replay. Bronze remains the source of recovery evidence.
-- NULL bounds perform a deterministic full candidate rebuild. A bounded replay assumes the
-- candidate already has a correct baseline outside the requested window.
CREATE OR REPLACE PROCEDURE {names.replay_procedure}(
    P_FROM TIMESTAMP_NTZ DEFAULT NULL,
    P_TO TIMESTAMP_NTZ DEFAULT NULL
)
RETURNS OBJECT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    V_REPAIR_ID VARCHAR DEFAULT UUID_STRING();
    V_ROWS_READ NUMBER DEFAULT 0;
    V_ROWS_RECOVERED NUMBER DEFAULT 0;
{IDEMPOTENCY_DECLARATIONS}BEGIN
{_range_guard(timestamp_column)}    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_REPLAY_INPUT (
{new_defs}
    );

    INSERT INTO ESF_REPLAY_INPUT ({_csv(columns)})
    SELECT {_csv(columns, 'B')}
    FROM {names.bronze_relation} B
    WHERE {row_filter};

    V_ROWS_READ := (SELECT COUNT(*) FROM ESF_REPLAY_INPUT);

{_repair_start(names)}    BEGIN
        BEGIN TRANSACTION;

{conflict_guard}        IF (P_FROM IS NULL AND P_TO IS NULL) THEN
            DELETE FROM {names.physical_relation};
        END IF;

        INSERT INTO {names.physical_relation} ({_csv(columns)}, ESF_LOADED_AT)
        SELECT {_csv(columns, 'N')}, CURRENT_TIMESTAMP()
        FROM {deduped_input}
        WHERE NOT EXISTS (
            SELECT 1
            FROM {names.physical_relation} T
            WHERE {dedup}
        );

        V_ROWS_RECOVERED := SQLROWCOUNT;
        COMMIT;
{_repair_failure()}{_repair_success()}"""


def _render_scd1_replay(names: PipelineNames, contract: dict[str, Any]) -> str:
    assert names.physical_relation
    columns = column_names(contract)
    business_key = [str(value).upper() for value in contract.get("business_key", [])]
    ordering = ordered_columns(contract)
    timestamp_column = _replay_timestamp(contract)
    row_filter = _range_filter(timestamp_column)
    order_desc = ", ".join(f"{name} DESC" for name in ordering) or ", ".join(
        f"{name} DESC" for name in business_key
    )
    join = _join("T", "N", business_key)
    assignments = [f"T.{name} = N.{name}" for name in columns if name not in business_key]
    assignments.append("T.ESF_LOADED_AT = CURRENT_TIMESTAMP()")
    update_set = ",\n            ".join(assignments)
    delete_expr = _tombstone_expression(contract, "N")
    return f"""-- Candidate SCD1 replay/current-state rebuild from Bronze evidence.
-- NULL bounds clear and deterministically rebuild the candidate current state. A bounded replay
-- assumes the candidate already has a correct baseline outside the requested window.
CREATE OR REPLACE PROCEDURE {names.replay_procedure}(
    P_FROM TIMESTAMP_NTZ DEFAULT NULL,
    P_TO TIMESTAMP_NTZ DEFAULT NULL
)
RETURNS OBJECT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    V_REPAIR_ID VARCHAR DEFAULT UUID_STRING();
    V_ROWS_READ NUMBER DEFAULT 0;
    V_ROWS_RECOVERED NUMBER DEFAULT 0;
BEGIN
{_range_guard(timestamp_column)}{_repair_start(names)}    BEGIN
        BEGIN TRANSACTION;

        IF (P_FROM IS NULL AND P_TO IS NULL) THEN
            DELETE FROM {names.physical_relation};
        END IF;

        V_ROWS_READ := (
            SELECT COUNT(*)
            FROM {names.bronze_relation} B
            WHERE {row_filter}
        );

        MERGE INTO {names.physical_relation} T
        USING (
            SELECT {_csv(columns)}
            FROM {names.bronze_relation} B
            WHERE {row_filter}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY {_csv(business_key)}
                ORDER BY {order_desc}
            ) = 1
        ) N
        ON {join}
        WHEN MATCHED AND {delete_expr} THEN DELETE
        WHEN MATCHED THEN UPDATE SET
            {update_set}
        WHEN NOT MATCHED AND NOT {delete_expr} THEN INSERT (
            {_csv(columns)}, ESF_LOADED_AT
        ) VALUES (
            {_csv(columns, 'N')}, CURRENT_TIMESTAMP()
        );

        V_ROWS_RECOVERED := SQLROWCOUNT;
        COMMIT;
{_repair_failure()}{_repair_success()}"""


def _render_full_refresh_replay(names: PipelineNames, contract: dict[str, Any]) -> str:
    assert names.physical_relation
    columns = column_names(contract)
    return f"""-- Candidate full-refresh rebuild from the current Bronze snapshot.
-- Full-refresh has snapshot semantics, so this procedure deliberately has no time-range parameters.
CREATE OR REPLACE PROCEDURE {names.replay_procedure}()
RETURNS OBJECT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    V_REPAIR_ID VARCHAR DEFAULT UUID_STRING();
    V_ROWS_READ NUMBER DEFAULT 0;
    V_ROWS_RECOVERED NUMBER DEFAULT 0;
BEGIN
{_repair_start(names, range_values=False)}    BEGIN
        BEGIN TRANSACTION;

        V_ROWS_READ := (SELECT COUNT(*) FROM {names.bronze_relation});

        INSERT OVERWRITE INTO {names.physical_relation} ({_csv(columns)}, ESF_LOADED_AT)
        SELECT {_csv(columns)}, CURRENT_TIMESTAMP()
        FROM {names.bronze_relation};

        V_ROWS_RECOVERED := SQLROWCOUNT;
        COMMIT;
{_repair_failure()}{_repair_success()}"""


def _render_scd2_replay(names: PipelineNames, contract: dict[str, Any]) -> str:
    assert names.events_relation and names.history_relation
    columns = column_names(contract)
    business_key = [str(value).upper() for value in contract.get("business_key", [])]
    idempotency = [str(value).upper() for value in contract.get("idempotency_key", [])]
    ordering = ordered_columns(contract)
    source_timestamp = str(contract.get("source_timestamp", "")).upper()
    tracked = tracked_columns(contract)
    if not source_timestamp or not ordering or not tracked:
        raise ValueError("scd2 replay requires source_timestamp, ordering columns and tracked columns")
    key_defs = _typed_defs(contract, business_key)
    changes = contract.get("change_semantics", {})
    if changes.get("delete_semantics") == "tombstone" and changes.get("operation_column"):
        op = str(changes["operation_column"]).upper()
        values = ", ".join(
            "'" + str(value).replace("'", "''").upper() + "'"
            for value in changes.get("delete_values", [])
        )
        replay_action = f"IFF(UPPER(COALESCE(TO_VARCHAR(B.{op}), '')) IN ({values}), 'DELETE', 'INSERT')"
    else:
        replay_action = "'INSERT'"
    event_identity = [*idempotency, "ESF_STREAM_ACTION"]
    event_payload = [*columns, "ESF_STREAM_ACTION", "ESF_STREAM_ISUPDATE"]
    new_defs = _column_defs(contract)
    dedup = render_identity_join("E", "N", event_identity)
    conflict_guard = render_idempotency_conflict_guard(
        "ESF_REPLAY_INPUT",
        identity_columns=event_identity,
        payload_columns=event_payload,
    )
    deduped_input = render_deduped_relation(
        "ESF_REPLAY_INPUT",
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

    return f"""-- Historical candidate bootstrap/replay.
-- Requires Bronze to retain the full_change/full_event evidence declared by the RAW contract.
-- NULL bounds clear candidate evidence/history and deterministically rebuild all retained history.
-- A bounded replay assumes the candidate already has a correct baseline outside the requested window.
CREATE OR REPLACE PROCEDURE {names.replay_procedure}(
    P_FROM TIMESTAMP_NTZ DEFAULT NULL,
    P_TO TIMESTAMP_NTZ DEFAULT NULL
)
RETURNS OBJECT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    V_REPAIR_ID VARCHAR DEFAULT UUID_STRING();
    V_ROWS_READ NUMBER DEFAULT 0;
    V_ROWS_RECOVERED NUMBER DEFAULT 0;
{IDEMPOTENCY_DECLARATIONS}BEGIN
    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_REPLAY_INPUT (
{new_defs},
        ESF_STREAM_ACTION VARCHAR NOT NULL,
        ESF_STREAM_ISUPDATE BOOLEAN NOT NULL
    );

    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_AFFECTED_KEYS (
{key_defs}
    );

    INSERT INTO ESF_REPLAY_INPUT ({_csv(columns)}, ESF_STREAM_ACTION, ESF_STREAM_ISUPDATE)
    SELECT {_csv(columns, 'B')}, {replay_action}, FALSE
    FROM {names.bronze_relation} B
    WHERE (:P_FROM IS NULL OR B.{source_timestamp} >= :P_FROM)
      AND (:P_TO IS NULL OR B.{source_timestamp} < :P_TO);

    V_ROWS_READ := (SELECT COUNT(*) FROM ESF_REPLAY_INPUT);

{_repair_start(names)}    BEGIN
        BEGIN TRANSACTION;

{conflict_guard}        IF (P_FROM IS NULL AND P_TO IS NULL) THEN
            DELETE FROM {names.history_relation};
            DELETE FROM {names.events_relation};
        END IF;

        INSERT INTO {names.events_relation} (
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

        INSERT INTO ESF_AFFECTED_KEYS ({_csv(business_key)})
        SELECT DISTINCT {_csv(business_key, 'B')}
        FROM ESF_REPLAY_INPUT B;

        DELETE FROM {names.history_relation} H
        USING ESF_AFFECTED_KEYS K
        WHERE {affected_history};

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
                    TRUE, FALSE
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

        V_ROWS_RECOVERED := SQLROWCOUNT;
        COMMIT;
{_repair_failure()}{_repair_success()}"""


def render_replay_sql(pattern: str, names: PipelineNames, contract: dict[str, Any]) -> str:
    if pattern == "append":
        return _render_append_replay(names, contract)
    if pattern == "scd1":
        return _render_scd1_replay(names, contract)
    if pattern == "full_refresh":
        return _render_full_refresh_replay(names, contract)
    if pattern == "scd2":
        return _render_scd2_replay(names, contract)
    if pattern == "custom":
        return (
            f"-- {names.dataset_key} {names.version}: custom replay is domain-owned.\n"
            "-- Define explicit recovery SQL only after the domain documents its replay evidence and invariants.\n"
        )
    raise ValueError(f"unsupported pattern: {pattern}")
