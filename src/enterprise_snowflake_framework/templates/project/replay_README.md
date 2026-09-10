# Replay

Replay means the required source evidence is already correct in Bronze and Silver needs to be reprocessed.

Typical reasons:

- corrected transformation logic
- candidate-version rebuild
- controlled reprocessing of a known time/key range

Preferred production repair path:

```text
active version remains serving
  -> scaffold/deploy candidate
  -> generate/review candidate repair SQL
  -> bootstrap/replay candidate from Bronze
  -> catch up
  -> compare / validate
  -> explicit release SQL
  -> activate candidate
```

Standard pattern replay semantics are intentionally different:

```text
append       -> idempotent event replay
scd1         -> current-state rebuild/merge from ordered Bronze evidence
scd2         -> affected-key history rebuild
full_refresh -> complete current Bronze snapshot rebuild
custom       -> domain-authored
```

For a newly created empty candidate, prefer a full bootstrap with no time bounds. A bounded replay assumes the candidate already has a correct baseline outside that range. Full-refresh does not support time-range replay.

Do not use replay to hide missing Bronze data. If Bronze is incomplete, repair/backfill ingestion first.

`esf repair-sql` generates explicit candidate-only SQL/scripts for review. Engineers execute approved repair SQL; project initialization never runs replay automatically.
