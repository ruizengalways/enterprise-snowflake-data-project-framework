# Release operations

Release scripts are generated for review and explicit execution. `esf` never activates or rolls back a dataset by connecting to Snowflake.

Typical flow:

```text
active v1
  -> scaffold-version v2
  -> deploy candidate SQL
  -> replay/bootstrap
  -> catch up / shadow
  -> validate and reconcile
  -> release-sql v1 -> v2
  -> engineer reviews activate.sql / rollback.sql
```

Keep the active version available through the approved rollback window. Generated release directories are ownership units: if a target release directory already exists, the framework changes zero bytes.
