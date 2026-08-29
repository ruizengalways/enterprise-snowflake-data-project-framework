from __future__ import annotations

from dataclasses import asdict, dataclass

from .workspaces import STANDARD_LAYERS, normalize_token, validate_identifier

_ENVIRONMENTS = {"dev", "ci", "uat", "prod"}
_WORKLOADS = {"query", "transform", "ci"}


@dataclass(frozen=True)
class DbtTarget:
    project_code: str
    environment: str
    workload: str
    database: str
    warehouse: str
    schema_prefix: str
    default_schema: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    def as_env(self) -> dict[str, str]:
        return {
            "ESF_PROJECT_CODE": self.project_code,
            "ESF_ENVIRONMENT": self.environment,
            "ESF_SCHEMA_PREFIX": self.schema_prefix,
            "DBT_DATABASE": self.database,
            "DBT_WAREHOUSE": self.warehouse,
            "DBT_DEFAULT_SCHEMA": self.default_schema,
        }


def resolve_dbt_target(
    project_code: str,
    environment: str,
    workload: str,
    *,
    developer: str | None = None,
    pr_number: int | None = None,
    default_schema: str = "STAGING",
) -> DbtTarget:
    """Resolve canonical physical Snowflake targets without hard-coding them in model SQL."""
    code = validate_identifier(project_code, label="project code")
    environment = environment.strip().lower()
    workload = workload.strip().lower()
    default_schema = validate_identifier(default_schema, label="default schema")

    if environment not in _ENVIRONMENTS:
        raise ValueError(f"unsupported environment: {environment}")
    if workload not in _WORKLOADS:
        raise ValueError(f"unsupported workload: {workload}")
    if default_schema not in STANDARD_LAYERS:
        raise ValueError(f"unsupported default schema: {default_schema}")

    if environment == "ci":
        if workload != "ci":
            raise ValueError("CI environment must use the ci workload")
        if pr_number is None or pr_number <= 0:
            raise ValueError("CI environment requires pr_number > 0")
        if developer:
            raise ValueError("CI environment does not use developer workspace prefixes")
        database = f"CI_{code}"
        warehouse = f"WH_{code}_CI"
        schema_prefix = f"PR_{pr_number}"
    else:
        if workload == "ci":
            raise ValueError("ci workload is valid only in the CI environment")
        database = f"{environment.upper()}_{code}"
        warehouse = f"WH_{code}_{workload.upper()}"
        schema_prefix = ""

        if environment == "dev" and developer:
            schema_prefix = normalize_token(developer)
        elif environment != "dev" and developer:
            raise ValueError("developer workspace prefixes are valid only in DEV")
        if pr_number is not None:
            raise ValueError("pr_number is valid only in CI")

    return DbtTarget(
        project_code=code,
        environment=environment,
        workload=workload,
        database=database,
        warehouse=warehouse,
        schema_prefix=schema_prefix,
        default_schema=default_schema,
    )
