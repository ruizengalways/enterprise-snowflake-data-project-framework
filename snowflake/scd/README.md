# Stateful Silver correctness

`esf_scd2_history` is the authoritative standard SCD2 implementation.

It maintains a technical `<history>__ESF_EVENTS` table containing deterministic landed events already visible to Snowflake. Each run:

1. stages the readable domain SELECT;
2. deduplicates deterministic event identity;
3. identifies newly landed events and affected business keys;
4. rebuilds complete history only for those keys from retained event evidence;
5. atomically appends new events and replaces affected history rows.

This preserves replay/idempotency, late-arriving repair, tombstone delete/reinsert behavior, `valid_from`, `valid_to`, `is_current` and deterministic `version_order` without rebuilding unrelated keys.

The sidecar is Framework processing state, not a connector checkpoint or replacement for Bronze evidence. If the history target is emptied/reset while the sidecar remains, missing keys are detected and rebuilt from the ledger.

Dynamic Tables are deliberately not the standard state-maintenance engine for this history. Consumers should read `<entity>_current` views instead of duplicating `where is_current = true` throughout Gold.
