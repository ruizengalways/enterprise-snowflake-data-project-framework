# Repair operations

## Principle

Repair starts from the most recent layer known to be correct.

```text
Source
  -> Bronze
  -> Silver
  -> Gold/dbt
```

The framework should help engineers diagnose impact and generate explicit repair SQL/scripts. The first repair implementation does not autonomously execute production repair.

## Failure classification

### Ingestion failure

If Bronze is incomplete or wrong, repair Source -> Bronze first using the technology that owns ingestion.

Examples:

- Openflow: connector recovery/backfill
- Snowpipe: stage/pipe/COPY repair
- Kafka: connector replay/offset controls
- API: cursor/watermark replay when domain-owned
- Talend/ADF/Informatica: rerun in the external orchestrator

The framework does not emulate these connectors.

After Bronze is corrected, replay affected Silver and rebuild affected downstream dbt models.

### Silver failure

If Bronze is correct and Silver logic is wrong, the default repair is a new candidate version rather than ad-hoc mutation of the active history table.

```text
fix code
  -> create candidate version
  -> replay Bronze
  -> catch up
  -> shadow compare
  -> validate
  -> activate
```

The active version remains available while the repair candidate is built.

### Gold/dbt failure

If Silver is correct, fix dbt code and rebuild only the affected model graph from Silver. Do not rerun ingestion or Silver without evidence that those layers are wrong.

## Replay, backfill and reset

These operations have different meanings and must remain separate.

### Replay

Data already exists correctly in Bronze. Reprocess Bronze -> Silver, usually after a transformation fix or version rebuild.

### Backfill

Required historical data never entered the platform. Recover Source -> Bronze, then process downstream layers.

### Reset

Discard/recreate a development or candidate implementation so it can be bootstrapped again. Reset is primarily for DEV/UAT/candidate objects, not a default production repair mechanism.

## Bronze retention

Replayability depends on Bronze retaining enough evidence.

CDC/event pipelines should preserve source changes and ordering evidence for the required recovery window. If the ingestion strategy only captures current snapshots, intermediate history that never reached Bronze cannot be reconstructed by an SCD2 procedure.

Bronze retention therefore belongs in the operational design of every dataset.

## REPAIR_RUN

Every executed repair should be auditable regardless of the technology that performs it.

Recommended fields:

- repair_id
- dataset_id
- repair_type (`INGESTION`, `SILVER_REPLAY`, `DBT_REBUILD`, `BACKFILL`, `RESET`)
- reason
- requested_from
- requested_to
- started_at
- completed_at
- status
- rows_recovered
- operator
- git_commit
- external_run_id
- error details

## Repair planner

The framework should provide a read-only planner before it provides automation.

Conceptual command:

```text
esf repair-plan customer --source fleet_mssql --problem silver --from <timestamp>
```

Output should identify:

- problem layer
- known-good layer
- active version
- recommended candidate version
- Bronze replay range
- validation requirements
- affected downstream dbt models when known
- whether active production objects will be overwritten (default: no)

## Repair SQL generation

The first executable aid should generate explicit SQL/scripts into the repository or a user-selected output path. Engineers review and run those scripts themselves.

Generated repair scripts must:

1. identify the target dataset and version explicitly;
2. avoid hidden metadata-driven routing;
3. avoid modifying active production data unless the script makes that action obvious;
4. preserve the active version while a repair candidate is built when practical;
5. record/describe the expected `REPAIR_RUN` audit entry;
6. be safe to review in Git or change-management tooling.

The framework must not introduce a one-command autonomous `repair everything` engine in the first implementation.

## Downstream rebuild

After a Silver repair is activated, rebuild only affected dbt descendants where practical. A repair plan should make this dependency explicit rather than automatically rerunning the whole domain.

## Incident closure

Repair completion and incident resolution are separate facts.

A repair may complete successfully but health validation can still fail. An incident is resolved only after the affected health/SLA/DQ conditions recover.
