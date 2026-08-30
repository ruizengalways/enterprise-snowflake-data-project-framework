# Domain-Scoped Operational Control

Project runtime access to account-local `PLATFORM_CONTROL.OPERATIONS` state must use the domain-scoped contract provisioned by `enterprise-snowflake-platform-infra`.

## Boundary

Shared base objects remain platform-owned:

```text
PIPELINE_CHECKPOINT
PIPELINE_RUN
PIPELINE_CHECK_RESULT
```

Project deployment roles must not require direct DML on those shared tables. Instead, platform-infra generates for each project code:

```text
<DOMAIN>_PIPELINE_CHECKPOINT
<DOMAIN>_PIPELINE_RUN
<DOMAIN>_PIPELINE_CHECK_RESULT

<DOMAIN>_ADVANCE_PIPELINE_CHECKPOINT(...)
<DOMAIN>_PIPELINE_RUN_START(...)
<DOMAIN>_PIPELINE_RUN_FINISH(...)
<DOMAIN>_RECORD_PIPELINE_CHECK_RESULT(...)
```

The read surfaces are filtered by a server-fixed `PROJECT_CODE`. The write procedures also fix project and account environment inside the procedure body; callers do not submit either value.

## Framework helpers

Use these project-runtime helpers:

```text
esf_domain_checkpoint_read_sql()
esf_domain_checkpoint_advance_call_sql()
esf_domain_pipeline_run_start_call_sql()
esf_domain_pipeline_run_finish_call_sql()
esf_domain_record_check_result_sql()
```

They derive the approved relation/procedure name from the validated project code.

Example checkpoint read:

```jinja
{{ enterprise_snowflake_framework.esf_domain_checkpoint_read_sql(
    'TRANSPORT',
    'vehicle_position',
    'source_position'
) }}
```

This targets:

```text
PLATFORM_CONTROL.OPERATIONS.TRANSPORT_PIPELINE_CHECKPOINT
```

Example checkpoint advance:

```jinja
{{ enterprise_snowflake_framework.esf_domain_checkpoint_advance_call_sql(
    'TRANSPORT',
    'vehicle_position',
    'source_position',
    "object_construct('offset', 12345)",
    'batch-123',
    'full-git-sha'
) }}
```

The generated `CALL` does not pass `TRANSPORT` as a procedure argument. The procedure name itself selects the guarded domain API.

## Run ledger

Run start and finish use domain procedures rather than direct shared-table DML:

```jinja
{{ enterprise_snowflake_framework.esf_domain_pipeline_run_start_call_sql(
    'TRANSPORT',
    'run-123',
    1,
    'vehicle_position_capture',
    'vehicle_position',
    'full-git-sha'
) }}
```

```jinja
{{ enterprise_snowflake_framework.esf_domain_pipeline_run_finish_call_sql(
    'TRANSPORT',
    'run-123',
    1,
    'SUCCEEDED',
    "object_construct('offset', 12345)",
    '100',
    '100'
) }}
```

The platform procedure enforces domain and environment when matching the run row.

## Quality/check results

`esf_domain_record_check_result_sql()` accepts a framework check query and emits a Snowflake Scripting block that iterates over its result rows and calls the guarded domain procedure once per result.

This preserves the existing reusable check-query contract while avoiding project INSERT privilege on the shared check-result table.

## Lower-level compatibility primitives

The older macros below remain available as lower-level building blocks:

```text
esf_checkpoint_read_sql()
esf_checkpoint_advance_call_sql()
esf_pipeline_run_start_sql()
esf_pipeline_run_finish_sql()
esf_record_check_result_sql()
```

They accept explicit relations/procedures and some emit direct DML. Do not use them from a project runtime role against shared `PLATFORM_CONTROL.OPERATIONS` base tables.

They remain useful for isolated/private state, platform-owned execution, compatibility, and tests. New project runtime integration should use the `esf_domain_*` contract.

## Verification status

Framework source/static CI can prove macro discovery, project-code validation and intended SQL shape. It cannot prove Snowflake grants or owner-rights behavior.

Live DEV must still prove cross-domain invisibility/denial, own-domain read/write, absence of direct shared-table DML privileges, retry/idempotency behavior and checkpoint transaction composition before this boundary is considered production-proven.
