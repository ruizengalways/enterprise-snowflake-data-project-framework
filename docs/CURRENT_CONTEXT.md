# Current Context

Concise handoff for a new conversation.

## Framework role

The framework is an **optional enterprise adapter/accelerator**, not the host of domain data repositories.

Domain repositories must keep a framework-independent portable core that owns source contracts and can generate representative synthetic Snowflake data without installing this framework.

Dependency direction:

```text
portable domain repo core
  contracts / domain metadata / standalone SQL
            ↑
optional enterprise adapter
            ↑
this framework + platform infra
```

Do not introduce a framework capability that makes a domain source contract or demo-data generator impossible to use without this repository.

Current portability references:

```text
Transport PR #5
  Standalone SQL CI #1: SUCCESS
  DEMO_TRANSPORT source simulation

Health PR #4
  Standalone SQL CI #1: SUCCESS
  DEMO_HEALTH source simulation
```

The standalone paths contain no framework or `PLATFORM_CONTROL` dependency. A plain-Snowflake live execution is still required for portability live proof.

## Active framework stack

```text
PR #2 metadata-driven SCD2
 -> PR #3 bootstrap handoff
 -> PR #4 Medallion/config snapshot/stable deployment
 -> PR #5 generation-aware reset helpers
```

Current immutable reset-aware framework pin:

```text
8afe208bd911a59b9334add78a53878ffea93087
Framework CI #181: SUCCESS
```

## Framework-owned enterprise conveniences

The framework may provide reusable behavior for:

```text
Medallion target/workspace conventions
metadata validation
SCD1/SCD2 helpers
bootstrap handoff
config snapshot hashing/registration
PLATFORM_CONTROL domain API helpers
stable deployment/WIF workflow
bounded full reset execution
```

These are enterprise integration capabilities. They must not redefine domain source meaning.

Capture semantics remain independent from target/history semantics. Genuine source/domain/business logic stays explicit in the domain repo; do not turn YAML into a programming language.

## Dataset config/audit

Git remains desired configuration truth for the enterprise adapter. Validated dataset + RAW technical metadata can be rendered into deterministic config snapshots and registered only through domain-scoped CONFIG APIs after successful deployment.

This CONFIG audit mechanism is not a requirement for the framework-free portable demo path.

## Full reset

Framework PR #5 provides bounded helpers:

```text
RESET_START
 -> explicit domain-owned relation list
 -> TRUNCATE TABLE IF EXISTS for validated relations
 -> RESET_COMPLETE
```

Repair/replay remains separate. The framework does not accept arbitrary runtime reset relation names through generic YAML.

Platform-infra PR #3 owns generation state and Recovery RBAC:

```text
c20c09c0c5f51dff17ebc5fb3eec75c89c5ce5a2
Terraform CI #167: SUCCESS
Platform Control SQL CI #37: SUCCESS
```

Same reset ID is retryable only while `RESETTING`; ready/completed IDs fail closed before cleanup.

## Enterprise deployment boundary

The reusable enterprise deployment flow remains:

```text
verify project SHA reachable from main
 -> verify immutable framework pin
 -> validate project metadata
 -> derive dbt context
 -> protected-environment WIF
 -> dbt build
 -> register CONFIG snapshots only after success
```

This flow is optional for a portable consumer. A team using a different Snowflake platform can ignore it and consume the domain repo contracts/standalone SQL directly.

## Proof tracks

```text
DOMAIN PORTABILITY
  proved independently by each domain's Standalone SQL CI

ENTERPRISE ADAPTER
  proved by framework/platform/dbt static suites
```

Static enterprise proof does not establish real WIF, Snowflake grants, cross-domain denial, transaction/concurrency behavior, reset/reload execution or real source CDC consistency.

## Next gates

Portable gate:

```text
plain Snowflake database
no framework package
no PLATFORM_CONTROL
 -> run domain standalone SQL
 -> verify expected demo rows/keys/CDC operations
```

Enterprise gate:

```text
bootstrap DEV + WIF
 -> deploy platform control
 -> prove domain isolation/runtime/bootstrap/config
 -> prove generation-aware reset
 -> connect deterministic external-style source
 -> prove snapshot -> incremental/CDC handoff
```
