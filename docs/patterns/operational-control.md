# Domain-scoped operational control v2

Project runtime access to account-local `PLATFORM_CONTROL.OPERATIONS` uses only domain-scoped views and guarded procedures provisioned by platform infra.

Shared base objects remain platform-owned. Project roles do not require direct DML on them.

## Domain surfaces

Typical scoped read surfaces:

```text
<DOMAIN>_PIPELINE_CHECKPOINT
<DOMAIN>_PIPELINE_RUN
<DOMAIN>_PIPELINE_CHECK_RESULT
<DOMAIN>_PIPELINE_BOOTSTRAP
```

Typical guarded write procedures:

```text
<DOMAIN>_ADVANCE_PIPELINE_CHECKPOINT
<DOMAIN>_PIPELINE_RUN_START
<DOMAIN>_PIPELINE_RUN_FINISH
<DOMAIN>_RECORD_PIPELINE_CHECK_RESULT
<DOMAIN>_PIPELINE_BOOTSTRAP_*
```

The project code/environment boundary is fixed by the platform-generated object, not supplied as arbitrary runtime DML predicates.

## Processing checkpoints only

Framework checkpoint helpers intentionally accept only landed-data processing checkpoint kinds. A checkpoint might record the last Bronze timestamp/batch/file/event boundary successfully incorporated into Silver.

It is not a source connector ledger. Do not put SQL Server LSNs, Kafka connector offsets or API extraction cursors here.

Example:

```jinja
{{ enterprise_snowflake_framework.esf_domain_checkpoint_read_sql(
    'TRANSPORT',
    'vehicle_position',
    'watermark'
) }}
```

The matching advance call writes through the guarded domain procedure rather than shared-table DML.

## Run and quality state

Run start/finish helpers register status, checkpoint-before/after, row counts and errors. DQ helpers record bounded check results through the domain procedure. These records provide operational answers beyond GitHub logs: dataset, last success, duration, rows, checkpoint and DQ state.

## No compatibility layer

V2 exposes the domain-scoped contract as the project runtime API. Deprecated lower-level compatibility aliases/direct-DML helpers are not part of the clean public surface.

## Live gate

Static tests can prove naming, validation and generated SQL shape. DEV/WIF acceptance must still prove grants, cross-domain denial, transaction behavior and real Snowflake procedure execution before those are claimed as live successes.
