# Template provenance and upgrade planning

## Purpose

The Framework generates a dataset implementation once and the domain owns that implementation from then on. A later Framework release must not silently rewrite domain SQL just because a scaffold template changed.

That ownership model creates a maintenance question: when a historical template revision is later found to need attention, how can an engineer know which generated implementations came from that revision?

Template provenance answers that question without turning the Framework into a runtime engine or an auto-upgrader.

## Generated provenance

Every implementation created by Framework 0.22.0 or later declares immutable generation identity in `version.yml`:

```yaml
version:
  dataset: fleet_mssql.customer
  id: v2
  initial_status: development
  activation: explicit
  execution_model: stream_task
  provenance:
    framework_version: 0.22.0
    template_id: scd2_stream_task
    template_revision: 1
    template_digest: sha256:...
```

The compatibility identity is the template id, revision and digest. `framework_version` records which Framework release performed the scaffold.

There is deliberately no `scaffolded_at` timestamp. Generation remains deterministic and compatibility does not depend on wall-clock time.

## Template revision registry

The Framework keeps an explicit immutable registry of template revisions. A template id combines the semantic pattern and execution model, for example:

- `scd2_stream_task`
- `scd1_dynamic_table`
- `full_refresh_batch_sql`

A revision's digest is calculated from its registered template identity and artifact contract. When a template changes in a compatibility-relevant way, the Framework must add a new revision and retain the old revision in the registry. Historical registry entries are not rewritten.

The digest is an identity check for the declared registry revision. It is not a hash of domain-owned SQL and is not used to decide whether an engineer has customized generated files.

## Legacy implementations

Implementations generated before provenance existed remain valid. If `version.yml` has no provenance block, `esf upgrade-plan` reports:

```text
status: UNKNOWN
reason: provenance is absent; template revision is UNKNOWN and is not inferred from SQL
```

This is intentional. The Framework does **not** inspect SQL comments, object names, formatting or other generated output to guess which template revision created an old implementation.

A malformed declaration is also not repaired or inferred. A declared digest that does not match the immutable registry is reported as `UNVERIFIED`.

## Read-only upgrade plan

Run:

```bash
esf upgrade-plan --project-root .
```

The command scans declared dataset versions and reports one of:

- `CURRENT`: declared identity matches the current registered template revision.
- `UPDATE_AVAILABLE`: a newer registered revision exists, but no advisory marks this revision unsafe.
- `ADVISORY`: one or more published advisories affect the declared revision.
- `UNKNOWN`: provenance is absent or references an identity this Framework cannot verify.
- `UNVERIFIED`: the declared digest does not match the immutable registry identity.

The command is planning only. It never edits a dataset, creates a candidate, changes Control state or executes Snowflake SQL. Its output ends with `No files changed.`

## Advisories

Advisories are explicit Framework data. They identify an affected `template_id` and maximum affected revision, plus severity, issue and recommended action.

The default advisory catalog is intentionally empty until a real released template revision needs an advisory. Tests use injected fixture advisories so matching behavior is covered without publishing a fabricated incident.

A future advisory should recommend an explicit domain-owned upgrade path, normally:

1. create a new candidate using the current template;
2. apply any required domain logic intentionally;
3. replay/bootstrap from retained Bronze evidence where appropriate;
4. run DQ and active-vs-candidate comparison;
5. release through the guarded release workflow.

The Framework must not mutate the historical implementation in place.

## Non-goals

Template provenance does not provide automatic code migration, SQL fingerprinting, runtime routing, candidate activation, or compatibility guesses for pre-provenance implementations. Those would weaken the generated-once ownership boundary rather than strengthen it.
