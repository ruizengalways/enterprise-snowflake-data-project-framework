# Repair operations

## Principle

Repair starts from the most recent layer known to be correct.

```text
Source
  -> Bronze
  -> Silver
  -> Gold/dbt
```

The framework helps engineers diagnose impact and generate explicit repair SQL/scripts. It does not autonomously execute production repair.

## Failure classification

### Ingestion failure

If Bronze is incomplete or wrong, repair Source -> Bronze first using the technology that owns ingestion.

Examples:

- Openflow: connector recovery/backfill
- Snowpipe: stage/pipe/COPY repair
- Kafka: connector replay/offset controls
- API: cursor/watermark replay when domain-owned
- Talend/ADF/Informatica: rerun in the external orchestrator

The framework does not emulate these connectors. After Bronze is corrected, replay affected Silver and rebuild affected downstream dbt models.

### Silver failure

If Bronze is correct and Silver logic is wrong, prefer a new candidate version rather than ad-hoc mutation of the active history table.

```text
fix code
  -> scaffold-version vN
  -> deploy candidate
  -> replay Bronze
  -> catch up
  -> validate
  -> compare
  -> release-sql
  -> explicit activation
```

The active version remains available while the repair candidate is built.

### Gold/dbt failure

If Silver is correct, fix dbt code and rebuild only the affected model graph from Silver. Do not rerun ingestion or Silver without evidence those layers are wrong.

## Replay, backfill and reset

### Replay

Data already exists correctly in Bronze. Reprocess Bronze -> Silver, usually after a transformation fix or candidate rebuild.

### Backfill

Required historical data never entered the platform. Recover Source -> Bronze, then process downstream layers.

### Reset

Discard/recreate a development or candidate implementation so it can be bootstrapped again. Reset is not a default production repair mechanism.

## Bronze retention

Replayability depends on Bronze retaining sufficient evidence. CDC/event pipelines should preserve source changes and ordering evidence for the required recovery window. If ingestion only captures current snapshots, intermediate history that never reached Bronze cannot be reconstructed by an SCD2 procedure.

## REPAIR_RUN

Every executed repair should be auditable regardless of the technology that performs it. The domain-local `CONTROL.REPAIR_RUN` table records repair identity, dataset, type, range, status, operator, Git commit/external run evidence, row counts and errors.

## `esf repair-plan`

Implemented as a read-only command:

```bash
esf repair-plan customer \
  --source fleet_mssql \
  --problem silver \
  --from "2026-09-01 00:00:00"
```

It identifies:

- problem layer
- known-good layer
- recommended action
- recommended next candidate version for Silver failures
- requested range
- whether active production will be overwritten (default `NO`)
- validation/catch-up/downstream checks

It writes zero files and executes zero Snowflake SQL.

## `esf repair-sql`

The first executable aid supports SCD2 candidate replay:

```bash
esf repair-sql customer v2 \
  --source fleet_mssql \
  --from "2026-09-01 00:00:00"
```

It creates an ownership unit under:

```text
operations/replay/fleet_mssql/customer/v2/
├── README.md
└── repair.sql
```

If that directory already exists, the framework changes zero bytes.

The generated SQL:

1. suspends only the candidate task;
2. calls the candidate-local replay procedure for the requested range;
3. leaves the active physical/published implementation untouched;
4. points engineers to candidate validation and catch-up;
5. requires release SQL to be generated separately after validation.

The replay procedure writes `CONTROL.REPAIR_RUN` evidence itself.

Other patterns remain domain-authored until their replay semantics are sufficiently stable to standardize safely.

## Candidate replay implementation

The generated SCD2 candidate keeps a version-local retained event ledger. Replay reads the Bronze evidence declared by the RAW contract, deduplicates with the idempotency key, identifies affected business keys and deterministically rebuilds only those keys in the candidate history table.

The online apply procedure and replay procedure use the same visible algorithmic ideas but are committed dataset-local SQL rather than calls into a central runtime SCD engine.

## Downstream rebuild

After a Silver repair is activated, rebuild only affected dbt descendants where practical. The framework does not automatically rerun the entire domain.

## Incident closure

Repair completion and incident resolution are separate facts. A repair may succeed while freshness, DQ or reconciliation checks still fail. Resolve the incident only after the affected health conditions recover.
