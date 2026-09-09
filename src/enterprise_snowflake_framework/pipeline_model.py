from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PipelineNames:
    source_id: str
    dataset_id: str
    dataset_key: str
    object_base: str
    entity: str
    version: str
    bronze_relation: str
    stream: str | None
    physical_relation: str | None
    events_relation: str | None
    history_relation: str | None
    current_relation: str | None
    published_relation: str | None
    published_history: str | None
    published_current: str | None
    apply_procedure: str
    replay_procedure: str
    task: str


def build_names(*, source_id: str, dataset_id: str, pattern: str, entity: str, version: str) -> PipelineNames:
    base = f"{source_id}_{dataset_id}".upper()
    entity_u = entity.upper()
    version_u = version.upper()
    stream = None if pattern in {"full_refresh", "custom"} else f"BRONZE.{base}_{version_u}_STREAM"
    physical = None
    events = None
    history = None
    current = None
    published_relation = None
    published_history = None
    published_current = None
    if pattern == "scd2":
        events = f"SILVER.{base}_{version_u}_EVENTS"
        history = f"SILVER.{base}_{version_u}_HISTORY"
        current = f"SILVER.{base}_{version_u}_CURRENT"
        published_history = f"SILVER.{base}_HISTORY"
        published_current = f"SILVER.{base}_CURRENT"
    elif pattern != "custom":
        physical = f"SILVER.{base}_{version_u}"
        published_relation = f"SILVER.{base}"
    return PipelineNames(
        source_id=source_id,
        dataset_id=dataset_id,
        dataset_key=f"{source_id}.{dataset_id}",
        object_base=base,
        entity=entity_u,
        version=version,
        bronze_relation=f"BRONZE.{base}",
        stream=stream,
        physical_relation=physical,
        events_relation=events,
        history_relation=history,
        current_relation=current,
        published_relation=published_relation,
        published_history=published_history,
        published_current=published_current,
        apply_procedure=f"SILVER.APPLY_{base}_{version_u}",
        replay_procedure=f"SILVER.REPLAY_{base}_{version_u}",
        task=f"SILVER.{base}_{version_u}_TASK",
    )


def _columns(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [column for column in contract.get("columns", []) if isinstance(column, dict)]


def column_names(contract: dict[str, Any]) -> list[str]:
    return [str(column["name"]).upper() for column in _columns(contract)]


def _column_defs(contract: dict[str, Any], indent: str = "    ") -> str:
    rendered = []
    for column in _columns(contract):
        nullable = "" if column.get("nullable", True) else " NOT NULL"
        rendered.append(f"{indent}{str(column['name']).upper()} {column['type']}{nullable}")
    return ",\n".join(rendered)


def _typed_defs(contract: dict[str, Any], names: list[str], indent: str = "    ") -> str:
    by_name = {str(column["name"]).upper(): column for column in _columns(contract)}
    return ",\n".join(f"{indent}{name} {by_name[name]['type']}" for name in names)


def _csv(names: list[str], alias: str | None = None) -> str:
    return ", ".join(f"{alias}.{name}" if alias else name for name in names)


def _join(left: str, right: str, names: list[str]) -> str:
    return " AND ".join(f"{left}.{name} = {right}.{name}" for name in names)


def tracked_columns(contract: dict[str, Any]) -> list[str]:
    changes = contract.get("change_semantics", {})
    excluded = {str(value).upper() for value in contract.get("business_key", [])}
    excluded.update(str(value).upper() for value in contract.get("ordering_columns", []))
    excluded.update(str(value).upper() for value in contract.get("idempotency_key", []))
    excluded.add("INGESTED_AT")
    if contract.get("source_timestamp"):
        excluded.add(str(contract["source_timestamp"]).upper())
    for key in ("operation_column", "sequence_column"):
        if changes.get(key):
            excluded.add(str(changes[key]).upper())
    return [name for name in column_names(contract) if name not in excluded]


def ordered_columns(contract: dict[str, Any]) -> list[str]:
    result: list[str] = []
    if contract.get("source_timestamp"):
        result.append(str(contract["source_timestamp"]).upper())
    for value in contract.get("ordering_columns", []):
        name = str(value).upper()
        if name not in result:
            result.append(name)
    return result


def _delete_expression(contract: dict[str, Any], alias: str) -> str:
    changes = contract.get("change_semantics", {})
    clauses = [f"({alias}.ESF_STREAM_ACTION = 'DELETE' AND NOT {alias}.ESF_STREAM_ISUPDATE)"]
    if changes.get("delete_semantics") == "tombstone" and changes.get("operation_column"):
        operation = str(changes["operation_column"]).upper()
        values = ", ".join(
            "'" + str(value).replace("'", "''").upper() + "'"
            for value in changes.get("delete_values", [])
        )
        if values:
            clauses.append(f"UPPER(COALESCE(TO_VARCHAR({alias}.{operation}), '')) IN ({values})")
    return "(" + " OR ".join(clauses) + ")"
