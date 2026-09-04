from __future__ import annotations

import re
from collections.abc import Iterable

STANDARD_LAYERS = (
    "BRONZE",
    "SILVER_STAGING",
    "SILVER_INTERMEDIATE",
    "SILVER_CANONICAL",
    "GOLD_MARTS",
    "GOLD_SEMANTIC",
    "DQ",
)
_IDENTIFIER_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_TOKEN_RE = re.compile(r"[^A-Z0-9]+")
_MAX_IDENTIFIER_LENGTH = 255


def normalize_token(value: str) -> str:
    """Convert an external identity token into a stable unquoted Snowflake token."""
    token = _TOKEN_RE.sub("_", value.strip().upper()).strip("_")
    token = re.sub(r"_+", "_", token)
    if not token:
        raise ValueError("token must contain at least one alphanumeric character")
    if token[0].isdigit():
        token = f"U_{token}"
    return token[:64]


def validate_identifier(value: str, *, label: str = "identifier") -> str:
    value = value.strip().upper()
    if len(value) > _MAX_IDENTIFIER_LENGTH or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"invalid unquoted Snowflake {label}: {value!r}")
    return value


def validate_layers(layers: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(validate_identifier(layer, label="layer") for layer in layers)
    unknown = sorted(set(normalized) - set(STANDARD_LAYERS))
    if unknown:
        raise ValueError(f"unsupported workspace layers: {', '.join(unknown)}")
    if not normalized:
        raise ValueError("at least one workspace layer is required")
    return normalized


def personal_schema_names(developer: str, layers: Iterable[str] = STANDARD_LAYERS) -> tuple[str, ...]:
    owner_token = normalize_token(developer)
    return tuple(f"{owner_token}_{layer}" for layer in validate_layers(layers))


def pr_schema_names(pr_number: int, layers: Iterable[str] = STANDARD_LAYERS) -> tuple[str, ...]:
    if pr_number <= 0:
        raise ValueError("PR number must be greater than zero")
    return tuple(f"PR_{pr_number}_{layer}" for layer in validate_layers(layers))


def render_create_schema_sql(
    database: str,
    schemas: Iterable[str],
    *,
    transient: bool,
    retention_days: int,
) -> str:
    database = validate_identifier(database, label="database")
    if retention_days not in (0, 1):
        raise ValueError("workspace retention must be 0 or 1 day")

    keyword = "TRANSIENT " if transient else ""
    comment = "ephemeral PR CI workspace" if transient else "developer workspace"
    statements: list[str] = []
    for schema in schemas:
        schema = validate_identifier(schema, label="schema")
        statements.append(
            f"CREATE {keyword}SCHEMA IF NOT EXISTS {database}.{schema} "
            f"DATA_RETENTION_TIME_IN_DAYS = {retention_days} "
            f"COMMENT = '{comment}; managed by enterprise-snowflake-data-project-framework';"
        )
    return "\n".join(statements)


def render_drop_schema_sql(database: str, schemas: Iterable[str], *, required_prefix: str) -> str:
    database = validate_identifier(database, label="database")
    prefix = validate_identifier(required_prefix, label="required prefix")
    statements: list[str] = []
    for schema in schemas:
        schema = validate_identifier(schema, label="schema")
        if not schema.startswith(prefix):
            raise ValueError(f"refusing to drop schema outside required prefix {prefix}: {schema}")
        statements.append(f"DROP SCHEMA IF EXISTS {database}.{schema};")
    return "\n".join(statements)
