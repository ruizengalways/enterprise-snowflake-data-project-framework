# Initial snapshot to incremental handoff

## Purpose

This pattern defines the reusable safety boundary for onboarding a source that needs an initial consistent snapshot before steady-state incremental or CDC processing begins.

Human guidance lives in `docs/`. Machine-readable source semantics live in the RAW contract under `contracts/raw/`. Runtime mutable state lives in `PLATFORM_CONTROL`. Source-specific extraction code stays in the domain/source implementation.

The framework deliberately does **not** describe how a particular database or API acquires a transaction-log position, cursor, LSN, SCN, offset, or consistent snapshot. Those mechanics remain source-specific.

## Machine contract

A source that supports a safe handoff declares only the reusable semantics:

```yaml
capture:
  archetype: full_change
  fidelity: full_change
  checkpoint_kind: source_position
  ordering_columns:
    - source_sequence
  idempotency_columns:
    - entity_id
    - source_sequence
  bootstrap:
    mode: snapshot_then_incremental
    snapshot_consistency: at_handoff_position
    incremental_start: exclusive
    reconciliation_required: true
```

`mode` states that an initial snapshot is followed by a different steady-state incremental capture path.

`snapshot_consistency: at_handoff_position` means the snapshot must represent source state at the recorded handoff boundary. The contract does not prescribe the vendor mechanism used to obtain that guarantee.

`incremental_start` defines boundary treatment:

- `exclusive` means steady-state capture starts strictly after the handoff position.
- `inclusive_with_deduplication` intentionally replays the boundary and therefore requires deterministic `idempotency_columns`.

`reconciliation_required: true` means the platform must not commit the handoff checkpoint until the landed snapshot has passed the required reconciliation gate.

## Runtime state machine

The platform-owned bootstrap state is intentionally small:

```text
BOUNDARY_CAPTURED
    -> SNAPSHOT_LANDED
    -> SNAPSHOT_VALIDATED
    -> HANDOFF_COMMITTED
```

A project runtime role sees only its domain-scoped secure view and invokes only its domain-fixed owner-rights procedures.

`SNAPSHOT_VALIDATED` is not inferred from arbitrary JSON text. The validation call supplies an explicit boolean reconciliation outcome plus structured details. The platform procedure rejects `FALSE` or `NULL`; only an explicit pass can advance the state. The details remain audit evidence and can describe row counts, key counts, source/target measures, or other source-specific checks.

The important final invariant is that `HANDOFF_COMMITTED` and the steady-state `PIPELINE_CHECKPOINT` are written in one transaction. A failed reconciliation therefore cannot advance the source checkpoint and silently create a permanent gap.

The initial-bootstrap API also refuses to start when a steady-state checkpoint already exists. At final commit it refuses to overwrite a different checkpoint value. Re-seeding an already-running dataset is deliberately treated as a separate operational workflow rather than hidden inside initial bootstrap.

## Recovery and retries

A bootstrap run has a stable `bootstrap_id`. Repeating an already-completed lifecycle call is idempotent where the recorded state proves the same lifecycle has already completed; conflicting boundary, snapshot identity, or reconciliation evidence fails closed.

Before `HANDOFF_COMMITTED`, recovery resumes from the recorded bootstrap state rather than inventing a new source position. After commit, normal checkpoint-driven processing owns progress.

The bootstrap table stores operational metadata only: source position, snapshot identifiers, timestamps, explicit reconciliation outcome/details, Git SHA, and status. It does not store business payloads or secrets.

## Framework API

Domain code should use the metadata-aware helpers in `dbt_package/macros/capture/bootstrap.sql`:

```jinja
{{ enterprise_snowflake_framework.esf_domain_bootstrap_start_call_sql(...) }}
{{ enterprise_snowflake_framework.esf_domain_bootstrap_snapshot_landed_call_sql(...) }}
{{ enterprise_snowflake_framework.esf_domain_bootstrap_validated_call_sql(
    project_code,
    dataset_id,
    bootstrap_id,
    reconciliation_passed_expression,
    reconciliation_details_expression
) }}
{{ enterprise_snowflake_framework.esf_domain_bootstrap_commit_handoff_call_sql(...) }}
```

The framework renders calls to domain-scoped platform procedures. It does not issue direct DML against shared `PLATFORM_CONTROL` base tables. SQL-expression arguments are compile-time checked for non-empty values before rendering.

## What remains source-specific

The following must remain explicit source/domain implementation unless repeated production use proves a bounded reusable contract is justified:

- acquiring the boundary position;
- starting or configuring source CDC/log retention;
- creating a transactionally consistent snapshot;
- mapping vendor-specific positions into the generic VARIANT checkpoint value;
- computing source-specific reconciliation checks and details;
- handling partial update images or source-specific log envelopes.

This separation keeps the metadata readable and prevents it from becoming a source-extraction programming language.

## Static versus live proof

Static CI can prove schema shape, semantic compatibility, bounded dbt metadata exposure, domain-scoped procedure names, explicit reconciliation-pass rendering, state-transition SQL shape, and the atomic checkpoint/state update contract.

Live DEV verification is still required for Snowflake transaction behavior, permissions, concurrent calls, retry behavior, cross-domain denial, and a real source's snapshot/position consistency guarantee.
