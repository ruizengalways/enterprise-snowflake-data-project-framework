# Next chat handoff

Read this file first when continuing the Framework in a new conversation, then read `docs/CURRENT_CONTEXT.md` and `docs/architecture/EXECUTION_MODELS.md`.

## Repository status

```text
repository = ruizengalways/enterprise-snowflake-data-project-framework
stable main before this feature = 4513df6d37953bd8b13660124281fafbd49a4ebb
stable version before this feature = 0.18.0
feature branch = feature/execution-model-dynamic-table
planned version = 0.19.0
```

The 0.19 work separates logical dataset semantics from implementation technology and adds first-class Dynamic Table support. Do not redesign that model in the next conversation; finish the current PR/CI/merge path first.

## Architecture contract

The key rule is:

```text
logical dataset
  pattern = semantic behavior

implementation version
  execution_model = Snowflake execution technology
```

`pattern` remains in the source manifest and logical `CONTROL.DATASET` metadata:

```text
append
full_refresh
scd1
scd2
custom
```

`execution_model` is version-specific:

```text
stream_task
dynamic_table
batch_sql
custom
```

Do not add `procedure` as an execution model. A procedure is an implementation artifact used by some execution models, not a peer of Stream+Task or Dynamic Table.

Compatibility is deliberately fail-closed in 0.19:

```text
append       + stream_task   = supported
full_refresh + stream_task   = supported
full_refresh + dynamic_table = supported
full_refresh + batch_sql     = supported
scd1         + stream_task   = supported
scd1         + dynamic_table = supported
scd2         + stream_task   = supported
custom       + custom        = supported/domain-owned

scd2         + dynamic_table = rejected
append       + dynamic_table = rejected
other unimplemented combinations = rejected
```

Do not broaden this matrix until equivalent semantics are explicitly implemented and certified.

## Generated implementation layouts

Legacy/default standard implementations remain `stream_task`, so existing domain behavior remains compatible.

A Stream+Task implementation owns the familiar explicit files such as object, apply, replay, validation, Task, registration and publication SQL.

A Dynamic Table implementation must not contain meaningless placeholder Stream/Task/procedure files. Its generated ownership unit is intentionally smaller:

```text
version.yml
001_dynamic_table.sql
020_validate.sql
025_compare.sql
040_register.sql
050_publish.sql
060_policy.sql
deploy_manifest.fragment.txt
README.md
```

Dynamic Table DQ is explicit dataset-local SQL that writes normalized `CONTROL.DQ_RESULT` evidence. The Framework does not create a fake apply procedure or fake pipeline-run ledger to make Dynamic Tables look like Stream+Task.

## Version metadata and Control Plane

New version contracts explicitly record `execution_model`. Legacy version files without it remain readable and default to `stream_task` for previously generated standard implementations.

Do not modify released Control migrations 001..080. New apply-once migrations are:

```text
090_dataset_execution_model.sql
100_dynamic_table_observability.sql
```

090 adds version-level execution metadata, including `EXECUTION_MODEL` and `PRIMARY_RUNTIME_OBJECT`, and backfills historical standard versions as `stream_task` where appropriate.

100 normalizes Dynamic Table runtime evidence from Snowflake-native `INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY`; it does not fabricate `CONTROL.PIPELINE_RUN` rows. `CONTROL.DATASET_OBSERVABILITY_V` chooses the evidence source based on the active version's execution model.

When upgrading an existing populated domain, rerun `esf init-project` to materialize missing migration files, review `esf control-plan`, append 090/100 to the domain-owned control manifest without reordering prior applied entries, and let `esf-control-preflight` enforce readiness.

## Dynamic Table execution contract

For `scd1 + dynamic_table`, current state is declarative: select the latest event per business key by the reviewed ordering tuple and filter tombstones. This preserves the SCD1 rule introduced in 0.18: late/out-of-order older evidence must not regress current state.

For `full_refresh + dynamic_table`, the Dynamic Table declares the current Bronze snapshot result.

Dynamic Table configuration is version policy, not logical SLA:

```text
target_lag   = Snowflake staleness target
refresh_mode = explicit incremental/full choice
warehouse    = Dynamic Table refresh warehouse

CONTROL.SLA_POLICY = separate business SLA
```

The Framework deliberately does not generate refresh mode `AUTO` in this first version.

## Lifecycle, release and repair

Lifecycle is execution-model aware:

```text
stream_task   -> ALTER TASK ... SUSPEND / RESUME
dynamic_table -> ALTER DYNAMIC TABLE ... SUSPEND / RESUME
batch_sql     -> coordinate the external scheduler explicitly
custom        -> domain-authored
```

Release may cross execution technologies. The reference 0.19 scenario is:

```text
customer v1: pattern=scd1, execution_model=stream_task
customer v2: pattern=scd1, execution_model=dynamic_table
```

Candidate deployment does not change stable consumer views. Explicit release/rollback still uses stable published views with `COPY GRANTS`. A Dynamic Table candidate is refreshed/validated before publication; old processing is retired only after publication/control updates.

Repair must not assume every candidate has a replay procedure or Task. Dynamic Table candidate repair uses explicit refresh/rebuild semantics and rejects bounded replay when that execution model cannot represent it safely.

## Certification

The trusted Snowflake certification layer remains post-main/approved and credential-free on untrusted PRs.

0.19 extends certification with a real cross-execution-model scenario:

```text
SCD1 v1 stream_task
  -> create v2 dynamic_table
  -> initial Dynamic Table refresh
  -> verify late/out-of-order equivalent current state
  -> insert new Bronze evidence after candidate creation
  -> v1 consumes through apply/Stream
  -> v2 refreshes natively
  -> compare outputs
  -> validate DQ
  -> verify native Dynamic Table refresh history
  -> cut over stable view with COPY GRANTS
  -> verify active health/runtime metadata
  -> rollback
```

Only a real Snowflake workflow artifact with `status = CERTIFIED` for the exact main SHA permits calling that SHA Snowflake-certified. Static CI alone is not certification.

## Stable guardrails that remain unchanged

- one business domain = one independent domain repository;
- one domain may contain many source systems;
- source profiling/discovery stays outside this Framework;
- RAW contracts require human review;
- generated SQL becomes domain-owned source code;
- no universal runtime metadata routing;
- no central SCD engine;
- no deployment-time scaffolding;
- CONTROL and SILVER use checksum-locked apply-once migrations;
- applied migration path/checksum/position are immutable;
- failed/started migrations block until reviewed remediation;
- new persistent version-owned objects are create-only/fail-closed;
- published view replacement is limited to explicit release/rollback and uses `COPY GRANTS`;
- dbt begins at trusted Silver and remains Gold/Mart/Semantic execution, never Bronze->Silver.

## Immediate next steps

In the next conversation, do this in order:

1. read this file, `docs/CURRENT_CONTEXT.md`, and `docs/architecture/EXECUTION_MODELS.md`;
2. re-check `main`, `feature/execution-model-dynamic-table`, open PRs and CI before writing;
3. inspect the final branch diff for accidental changes to released migrations or previous DDL/apply-once safety contracts;
4. run/open credential-free PR CI and fix real failures without weakening the execution-model contract;
5. merge only after the complete suite is green;
6. verify post-merge main CI;
7. update this handoff again with the final main SHA, PR number, CI run and live-certification status;
8. if Snowflake certification infrastructure is configured, run the trusted certification and treat any live failure as product evidence rather than weakening fixtures.

Until the merge is complete, describe the state as:

> 0.18.0 is the stable main baseline. 0.19.0 execution-model/Dynamic Table support is implemented on the feature branch and still requires final PR CI and merge validation.
