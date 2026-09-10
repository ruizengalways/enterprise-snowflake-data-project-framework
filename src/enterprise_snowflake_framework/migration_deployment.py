"""Public migration-deployment facade.

The state machine lives in ``migration_model``. Snowflake CLI/history persistence lives in
``migration_snowflake``. Keeping this facade stable makes the deployment contract easy to import
without coupling callers to the adapter layout.
"""

from .migration_model import (
    BLOCKING_STATUSES,
    MIGRATION_MANIFESTS,
    TERMINAL_SUCCESS_STATUSES,
    DeploymentIdentity,
    DeploymentResult,
    HistoryRecord,
    HistoryStore,
    MigrationBlocked,
    MigrationDecision,
    MigrationError,
    MigrationExecutor,
    MigrationFile,
    MigrationPlan,
    SnowCliError,
    baseline_existing_migrations,
    build_migration_plan,
    deploy_migrations,
    load_migrations,
    remediate_migration,
    sha256_file,
)
from .migration_snowflake import BOOTSTRAP_SQL, SnowCliClient, SnowflakeHistoryStore

__all__ = [
    "BLOCKING_STATUSES",
    "BOOTSTRAP_SQL",
    "MIGRATION_MANIFESTS",
    "TERMINAL_SUCCESS_STATUSES",
    "DeploymentIdentity",
    "DeploymentResult",
    "HistoryRecord",
    "HistoryStore",
    "MigrationBlocked",
    "MigrationDecision",
    "MigrationError",
    "MigrationExecutor",
    "MigrationFile",
    "MigrationPlan",
    "SnowCliClient",
    "SnowCliError",
    "SnowflakeHistoryStore",
    "baseline_existing_migrations",
    "build_migration_plan",
    "deploy_migrations",
    "load_migrations",
    "remediate_migration",
    "sha256_file",
]
