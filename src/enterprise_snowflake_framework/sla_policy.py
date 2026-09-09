from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .source_management import load_source_manifest

SLA_STAGES = {"SOURCE_TO_BRONZE", "BRONZE_TO_SILVER", "SILVER_TO_GOLD", "END_TO_END"}
CADENCE_TYPES = {"CONTINUOUS", "INTERVAL", "SCHEDULED_DEADLINE"}
_POLICY_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


@dataclass(frozen=True)
class SlaSqlResult:
    source_id: str
    dataset_id: str
    policy_id: str
    destination: Path
    created: bool


def _sql_string(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _sql_number(value: int | None) -> str:
    return "NULL" if value is None else str(value)


def _require_positive(name: str, value: int | None) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def generate_sla_sql(
    *,
    project_root: Path,
    source_id: str,
    dataset_id: str,
    policy_id: str,
    stage: str,
    cadence_type: str,
    max_latency_seconds: int | None = None,
    max_freshness_seconds: int | None = None,
    expected_interval_seconds: int | None = None,
    deadline_local_time: str | None = None,
    timezone: str | None = None,
    enabled: bool = True,
    output_root: Path | None = None,
) -> SlaSqlResult:
    project_root = project_root.resolve()
    if not _POLICY_ID.fullmatch(policy_id):
        raise ValueError("policy_id must match ^[a-z][a-z0-9_-]{1,63}$")
    stage = stage.upper()
    cadence_type = cadence_type.upper()
    if stage not in SLA_STAGES:
        raise ValueError(f"stage must be one of: {', '.join(sorted(SLA_STAGES))}")
    if cadence_type not in CADENCE_TYPES:
        raise ValueError(f"cadence must be one of: {', '.join(sorted(CADENCE_TYPES))}")
    for name, value in (
        ("max_latency_seconds", max_latency_seconds),
        ("max_freshness_seconds", max_freshness_seconds),
        ("expected_interval_seconds", expected_interval_seconds),
    ):
        _require_positive(name, value)

    manifest = load_source_manifest(project_root, source_id)
    if dataset_id not in manifest["datasets"]:
        raise KeyError(f"dataset is not declared in source manifest: {source_id}.{dataset_id}")

    if cadence_type == "INTERVAL" and expected_interval_seconds is None:
        raise ValueError("INTERVAL cadence requires expected_interval_seconds")
    if cadence_type != "INTERVAL" and expected_interval_seconds is not None:
        raise ValueError("expected_interval_seconds is only valid for INTERVAL cadence")
    if cadence_type == "SCHEDULED_DEADLINE":
        if not deadline_local_time or not timezone:
            raise ValueError("SCHEDULED_DEADLINE requires deadline_local_time and timezone")
    elif deadline_local_time is not None or timezone is not None:
        raise ValueError("deadline_local_time/timezone are only valid for SCHEDULED_DEADLINE cadence")
    if cadence_type == "CONTINUOUS" and max_latency_seconds is None and max_freshness_seconds is None:
        raise ValueError("CONTINUOUS cadence requires at least one latency or freshness threshold")

    dataset_key = f"{source_id}.{dataset_id}"
    root = (output_root or project_root / "operations" / "sla").resolve()
    destination = root / source_id / dataset_id / f"{policy_id}.sql"
    if destination.exists():
        return SlaSqlResult(source_id, dataset_id, policy_id, destination, False)
    destination.parent.mkdir(parents=True, exist_ok=True)

    deadline_sql = "NULL" if deadline_local_time is None else f"TO_TIME({_sql_string(deadline_local_time)})"
    sql = f"""-- Domain-owned SLA policy revision: {policy_id}
-- Generated for review. `esf` does not execute this file.
-- Dataset: {dataset_key}

MERGE INTO CONTROL.SLA_POLICY P
USING (
    SELECT
        '{dataset_key}' AS DATASET_ID,
        '{stage}' AS STAGE,
        '{cadence_type}' AS CADENCE_TYPE,
        {_sql_number(max_latency_seconds)} AS MAX_LATENCY_SECONDS,
        {_sql_number(max_freshness_seconds)} AS MAX_FRESHNESS_SECONDS,
        {_sql_number(expected_interval_seconds)} AS EXPECTED_INTERVAL_SECONDS,
        {deadline_sql} AS DEADLINE_LOCAL_TIME,
        {_sql_string(timezone)} AS TIMEZONE,
        {'TRUE' if enabled else 'FALSE'} AS ENABLED
) S
ON P.DATASET_ID = S.DATASET_ID AND P.STAGE = S.STAGE
WHEN MATCHED THEN UPDATE SET
    CADENCE_TYPE = S.CADENCE_TYPE,
    MAX_LATENCY_SECONDS = S.MAX_LATENCY_SECONDS,
    MAX_FRESHNESS_SECONDS = S.MAX_FRESHNESS_SECONDS,
    EXPECTED_INTERVAL_SECONDS = S.EXPECTED_INTERVAL_SECONDS,
    DEADLINE_LOCAL_TIME = S.DEADLINE_LOCAL_TIME,
    TIMEZONE = S.TIMEZONE,
    ENABLED = S.ENABLED,
    UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    DATASET_ID, STAGE, CADENCE_TYPE,
    MAX_LATENCY_SECONDS, MAX_FRESHNESS_SECONDS, EXPECTED_INTERVAL_SECONDS,
    DEADLINE_LOCAL_TIME, TIMEZONE, ENABLED
) VALUES (
    S.DATASET_ID, S.STAGE, S.CADENCE_TYPE,
    S.MAX_LATENCY_SECONDS, S.MAX_FRESHNESS_SECONDS, S.EXPECTED_INTERVAL_SECONDS,
    S.DEADLINE_LOCAL_TIME, S.TIMEZONE, S.ENABLED
);

-- Evaluate immediately after an approved policy change:
-- CALL CONTROL.EVALUATE_DOMAIN_HEALTH();
"""
    destination.write_text(sql, encoding="utf-8")
    return SlaSqlResult(source_id, dataset_id, policy_id, destination, True)
