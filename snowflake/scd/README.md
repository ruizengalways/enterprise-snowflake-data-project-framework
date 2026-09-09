# Stateful Silver correctness

The dbt `esf_scd2_history` materialization is the authoritative standard SCD2 implementation. It rebuilds deterministic history from retained landed/staging events, which makes replay and late-arrival handling idempotent by construction.

For very large histories, an optimized affected-key execution may replace the full rebuild only after live Snowflake acceptance proves identical semantics. The optimization boundary is technical: identify affected business keys, rebuild their complete retained event history in one transaction, and preserve `valid_from`, `valid_to`, `is_current`, and `version_order` semantics.

Dynamic Tables are deliberately not used to maintain this stateful history. Consumers should read `<entity>_current` views instead of duplicating `where is_current = true` throughout Gold.
