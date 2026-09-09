# Domain-scoped operational control

Account-local `PLATFORM_CONTROL` state is exposed through domain-scoped views and guarded procedures provisioned by platform infra. Shared base objects remain platform-owned; project roles do not receive direct DML on them.

Typical surfaces include domain-scoped pipeline runs, checks, landed-data processing checkpoints, bootstrap handoff and reset lifecycle procedures.

If explicit Silver SQL needs a control operation, call the guarded procedure directly from readable domain SQL or from the orchestrating workflow. Do not hide the call behind a dbt macro layer.

Processing checkpoints describe already-landed evidence only. Connector-owned source positions stay with the connector.

Snowflake-native runtime history remains authoritative where Snowflake owns the runtime, for example Task history. The control plane should add business/operational context rather than build a second scheduler.

Static tests prove naming and fail-closed contracts; DEV/WIF acceptance must still prove grants, cross-domain denial and real Snowflake procedure execution.
