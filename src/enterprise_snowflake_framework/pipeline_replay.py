from __future__ import annotations

from typing import Any

from .pipeline_model import (
    PipelineNames, _csv, _delete_expression, _join, _typed_defs, column_names,
    ordered_columns, tracked_columns,
)


def render_replay_sql(pattern: str, names: PipelineNames, contract: dict[str, Any]) -> str:
    if pattern != "scd2":
        return (
            f"-- {names.dataset_key} {names.version}: replay is pattern/source-specific.\n"
            "-- Add explicit replay SQL only when Bronze retains the required evidence.\n"
        )

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
    dedup = _join("E", "B", idempotency) + f" AND E.ESF_STREAM_ACTION = {replay_action}"
    affected_events = _join("E", "K", business_key)
    affected_history = _join("H", "K", business_key)
    state_hash = "TO_VARCHAR(HASH(" + _csv(tracked, "E") + "))"
    delete_expr = _delete_expression(contract, "E")
    order_e = ", ".join(f"E.{name}" for name in ordering)
    order_plain = ", ".join(ordering)

    return f"""-- Historical candidate bootstrap/replay.
-- Requires Bronze to retain the full_change/full_event evidence declared by the RAW contract.
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
BEGIN
    CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE ESF_AFFECTED_KEYS (
{key_defs}
    );

    INSERT INTO CONTROL.REPAIR_RUN (
        REPAIR_ID, DATASET_ID, REPAIR_TYPE, REQUESTED_FROM, REQUESTED_TO, STATUS, STARTED_AT, OPERATOR
    )
    SELECT
        :V_REPAIR_ID, '{names.dataset_key}', 'SILVER_REPLAY', :P_FROM, :P_TO,
        'RUNNING', CURRENT_TIMESTAMP(), CURRENT_USER();

    BEGIN
        BEGIN TRANSACTION;

        INSERT INTO {names.events_relation} (
            {_csv(columns)}, ESF_STREAM_ACTION, ESF_STREAM_ISUPDATE, ESF_EVENT_HASH, ESF_CAPTURED_AT
        )
        SELECT
            {_csv(columns, 'B')},
            {replay_action},
            FALSE,
            TO_VARCHAR(HASH({_csv(columns, 'B')}, {replay_action})),
            CURRENT_TIMESTAMP()
        FROM {names.bronze_relation} B
        WHERE (:P_FROM IS NULL OR B.{source_timestamp} >= :P_FROM)
          AND (:P_TO IS NULL OR B.{source_timestamp} < :P_TO)
          AND NOT EXISTS (
              SELECT 1
              FROM {names.events_relation} E
              WHERE {dedup}
          );

        V_ROWS_READ := SQLROWCOUNT;

        INSERT INTO ESF_AFFECTED_KEYS ({_csv(business_key)})
        SELECT DISTINCT {_csv(business_key, 'B')}
        FROM {names.bronze_relation} B
        WHERE (:P_FROM IS NULL OR B.{source_timestamp} >= :P_FROM)
          AND (:P_TO IS NULL OR B.{source_timestamp} < :P_TO);

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

        COMMIT;
    EXCEPTION
        WHEN OTHER THEN
            ROLLBACK;
            UPDATE CONTROL.REPAIR_RUN
            SET STATUS = 'FAILED', COMPLETED_AT = CURRENT_TIMESTAMP(),
                ERROR_CODE = TO_VARCHAR(SQLCODE), ERROR_MESSAGE = SQLERRM
            WHERE REPAIR_ID = :V_REPAIR_ID;
            RAISE;
    END;

    UPDATE CONTROL.REPAIR_RUN
    SET STATUS = 'SUCCESS', COMPLETED_AT = CURRENT_TIMESTAMP(), ROWS_RECOVERED = :V_ROWS_READ
    WHERE REPAIR_ID = :V_REPAIR_ID;

    RETURN OBJECT_CONSTRUCT('repair_id', V_REPAIR_ID, 'rows_recovered', V_ROWS_READ);
END;
$$;
"""
