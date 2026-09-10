# Safe dataset manifest editing

## Purpose

`esf add-dataset` removes a repetitive YAML-editing step without turning source manifests into a runtime control plane.

The source manifest remains developer-owned Git configuration. It declares only which datasets belong to a source and which scaffold pattern / RAW contract each dataset uses.

```text
reviewed RAW contract
  -> add-dataset
  -> source manifest declaration
  -> plan / scaffold-preview
  -> explicit committed Silver SQL
```

## Write boundary

The command may perform exactly one logical mutation: append a missing `datasets.<dataset_id>` entry.

It must not:

- change an existing dataset declaration;
- create or edit a RAW contract;
- create Silver SQL;
- create Snowflake objects;
- execute Snowflake;
- infer business keys, ordering, deletes or SCD semantics;
- rewrite another source manifest.

Existing dataset declarations are domain-owned. Re-running `add-dataset` returns a no-op even if the caller supplies different proposed arguments.

## YAML preservation

Source manifests are human-reviewed files, so broad `yaml.safe_dump(...)` rewrites are intentionally avoided. `add-dataset` uses round-trip YAML editing to retain existing comments, ordering and quoting where practical while appending the new map entry.

This is a readability feature, not a promise of byte-identical formatting for a successful append. The stronger byte-identical guarantee applies when the requested dataset already exists: no write occurs at all.

## RAW contract boundary

The default contract path is:

```text
contracts/raw/<source>/<dataset>.yml
```

A caller can supply `--raw-contract`, but it must remain under the same source directory. The file must already exist and its `contract.source_system` must match the source manifest.

This keeps source boundaries explicit and prevents accidentally declaring `fleet_mssql.customer` against a contract owned by `gtfs_api`.

## Pattern boundary

Supported declarations remain:

```text
append
full_refresh
scd1
scd2
custom
```

The selected pattern is developer-time scaffold intent. Production does not read the source manifest to dynamically route transformations.

## Recommended flow

```bash
esf add-source fleet_mssql --project-root .

# engineer creates/reviews contracts/raw/fleet_mssql/customer.yml

esf add-dataset customer \
  --source fleet_mssql \
  --pattern scd2 \
  --project-root .

esf plan --source fleet_mssql --project-root .
esf scaffold-preview customer --source fleet_mssql --project-root .
esf scaffold-all --source fleet_mssql --project-root .
esf validate --project-root .
```

There is deliberately no `--force`.
