# Repair operations

## Principle

Repair starts from the most recent layer known to be correct.

```text
Source -> Bronze -> Silver -> Gold/dbt
```

The framework helps engineers diagnose impact and generate explicit candidate repair SQL/scripts. It does not autonomously execute production repair.

## Failure classification

### Ingestion failure

If Bronze is incomplete or wrong, repair Source -> Bronze first using the technology that owns ingestion: Openflow, Snowpipe, Kafka, API code, Talend/ADF/Informatica, or another domain-specific implementation. The Framework does not emulate connector recovery or own connector checkpoints.

After Bronze is correct, replay the affected Silver candidate and rebuild affected downstream dbt models.

### Silver failure

If Bronze is correct and Silver logic is wrong, prefer a new candidate version rather than ad-hoc mutation of active production.

```text
fix code
  -> scaffold-version vN
  -> deploy candidate
  -> bootstrap/replay Bronze
  -> catch up
  -> validate + compare
  -> release-sql
  -> explicit activation
```

The active version remains available throughout repair.

### Gold/dbt failure

If Silver is correct, fix dbt code and rebuild only the affected model graph from Silver. Do not rerun ingestion or Silver without evidence those layers are wrong.

## Replay, backfill and reset

**Replay** means required data already exists correctly in Bronze and Bronze -> Silver must be recomputed.

**Backfill** means required historical data never entered the platform. Recover Source -> Bronze first, then process downstream.

**Reset** means discard/recreate a development or candidate implementation so it can be bootstrapped again. Reset is not the default production repair mechanism.

## Bronze retention

Replayability depends on Bronze retaining sufficient evidence. CDC/event pipelines should preserve source changes and ordering evidence for the required recovery window. If Bronze only contains a current snapshot, intermediate history that never reached Bronze cannot later be reconstructed as SCD2 history.

## Standard pattern repair semantics

The Framework standardizes four repair shapes at scaffold time. They are separate dataset-local procedures, not calls into one generic runtime engine.

### Append

`REPLAY_<dataset>_<version>(P_FROM, P_TO)` reads retained Bronze events and inserts only idempotency keys not already present in the candidate. With NULL bounds it is a full idempotent bootstrap.

### SCD1

`REPLAY_<dataset>_<version>(P_FROM, P_TO)` selects the latest ordered Bronze row per business key and merges it into the candidate current-state table. Tombstones declared by the RAW contract delete the candidate key.

### SCD2

The candidate keeps a version-local retained event ledger. Replay deduplicates Bronze evidence, identifies affected business keys and deterministically rebuilds history for those keys. Current state remains `IS_ACTIVE = TRUE`.

### Full refresh

`REPLAY_<dataset>_<version>()` rebuilds the candidate from the current complete Bronze snapshot using `INSERT OVERWRITE`. Time-range replay is deliberately unsupported because a full-refresh source has snapshot semantics.

### Custom

CUSTOM replay remains domain-authored. The Framework does not infer its recovery algorithm.

## Full bootstrap vs bounded replay

A newly created empty candidate should normally be bootstrapped with **no `--from` / `--to` bounds** so it contains the complete retained state/evidence required for activation.

A bounded replay is appropriate only when the candidate already has a known-correct baseline outside the requested range. `repair-plan`, generated SQL and generated README files state this explicitly.

## REPAIR_RUN

Every standard replay procedure writes the domain-local `CONTROL.REPAIR_RUN` ledger with repair identity, dataset, requested range where applicable, status, operator, recovered row count and error evidence.

Repair completion and incident resolution remain separate facts. A repair may succeed while freshness, DQ or reconciliation still fails.

## `esf repair-plan`

`repair-plan` is read-only:

```bash
esf repair-plan customer \
  --source fleet_mssql \
  --problem silver
```

It identifies the problem layer, latest known-good layer, recommended candidate version, replay/bootstrap expectation and validation/release checks. It writes zero files and executes zero Snowflake SQL.

## `esf repair-sql`

For standard patterns:

```bash
esf repair-sql customer v2 --source fleet_mssql
```

or, when a candidate baseline already exists and the pattern supports ranges:

```bash
esf repair-sql customer v2 \
  --source fleet_mssql \
  --from "2026-09-01 00:00:00" \
  --to   "2026-09-02 00:00:00"
```

It creates:

```text
operations/replay/<source>/<dataset>/<version>/
├── README.md
└── repair.sql
```

If that ownership unit already exists, the Framework changes zero bytes.

Generated repair SQL:

1. suspends only the candidate task;
2. calls the candidate-local replay procedure using pattern-appropriate arguments;
3. leaves active production and stable published objects untouched;
4. points engineers to candidate validation/catch-up;
5. requires separate `release-sql` after approval.

`full_refresh` rejects `--from`/`--to`. `custom` rejects `repair-sql` and remains domain-authored.

## Downstream rebuild

After a Silver repair is activated, rebuild only affected dbt descendants where practical. The Framework does not automatically rerun the whole domain.
