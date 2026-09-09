# Replay

Replay means the required source evidence is already correct in Bronze and Silver needs to be reprocessed.

Typical reasons:

- corrected SCD logic
- candidate-version rebuild
- transformation defect
- controlled reprocessing of a known time/key range

Preferred repair path for production Silver defects:

```text
active version remains serving
  -> generate/review candidate repair SQL
  -> build candidate from Bronze
  -> catch up
  -> compare / validate
  -> activate candidate
```

Do not use replay to hide missing Bronze data. If Bronze is incomplete, use a backfill/ingestion repair first.

Framework repair automation should generate explicit SQL/scripts for review. Engineers execute approved repair SQL; project initialization never runs replay automatically.
