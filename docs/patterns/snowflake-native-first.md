# Snowflake-native Silver processing

Bronze-to-Silver correctness uses explicit Snowflake SQL committed in each domain repository.

Preferred order:

```text
plain SQL when sufficient
  -> MERGE / transaction when stateful
  -> stored procedure when multi-step atomic logic is clearer
  -> Stream / Task when Snowflake-managed incremental execution is useful
```

Do not insert a shared macro/materialization layer between the domain engineer and those statements.

SCD1 and SCD2 are Silver correctness concerns. Their concrete SQL should show keys, ordering, delete behavior, replay handling and late-arrival behavior locally. Scaffolded starter files are copied once and then belong to the domain.

Dynamic Tables remain useful for declarative SELECT-defined results, especially Gold derivations, but are not the default engine for complex state/history maintenance.

`PLATFORM_CONTROL.OPERATIONS.PIPELINE_CHECKPOINT` may track processing progress over already-landed evidence. Stream offsets and connector offsets remain owned by their native runtimes.
