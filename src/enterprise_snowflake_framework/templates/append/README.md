# __DATASET_ID__ — append Silver pattern

This directory is copied into the domain repository once. Replace the TODO sections with the concrete column list from `__RAW_CONTRACT__` and keep the resulting SQL domain-owned.

The intended behavior is simple: preserve every distinct source event from `BRONZE.__ENTITY_UPPER__`, use the RAW-contract idempotency key to suppress delivery replay, and publish a trusted append relation in Silver.
