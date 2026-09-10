# Generated Snowflake DDL audit

This audit accompanies the DDL safety contract introduced in framework 0.17.0.

| Surface | Generated behavior | Replacement policy |
| --- | --- | --- |
| Version-owned Silver tables | `CREATE TABLE` | Create-only; collision fails. |
| Version-owned Streams | `CREATE STREAM` | Create-only; collision fails. |
| Version-local current views | `CREATE VIEW` | Create-only; not a stable consumer routing object. |
| Apply procedures | `CREATE PROCEDURE` in scaffold output | Create-only for the implementation version. |
| Replay procedures | `CREATE PROCEDURE` in scaffold output | Create-only for the implementation version. |
| Validation procedures | `CREATE PROCEDURE` | Create-only for the implementation version. |
| Dataset Tasks | `CREATE TASK` | Create suspended; activation is explicit. Never replace during normal scaffold deployment. |
| Initial stable published views | `CREATE VIEW` | Create-only; unexpected pre-existing stable name fails. |
| Candidate `050_publish.sql` | No publication DDL | Candidate deployment cannot change active consumer routing. |
| Release/rollback stable views | `CREATE OR REPLACE VIEW ... COPY GRANTS` | Intentional routing change; explicit grants except OWNERSHIP are preserved. |
| Procedure-scoped working tables | `CREATE OR REPLACE PROCEDURE SCOPED TEMP TABLE` | Intentional per-invocation temporary state; not a persistent object. |
| Released CONTROL migrations | Historical SQL remains immutable | Apply-once prevents replay. Fixes are appended as later migrations; released migration files are not edited. |
| dbt models | dbt desired-state build | Outside apply-once Silver migration semantics. |

## Audit conclusion

After apply-once deployment, the remaining unsafe production risk was not repeated execution of old files but replacement behavior inside newly applied DDL and explicit release scripts. Framework 0.17.0 narrows replacement to the stable published-view release boundary and invocation-scoped temporary work objects.

For persistent version-owned names, existence before their migration is an ownership conflict, not an idempotency condition. The migration runner already supplies idempotency at the file level.
