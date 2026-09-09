# __DATASET_ID__ — SCD2 Silver pattern

Keep the implementation visible in the domain repository.

Reference algorithm:

1. identify source events not yet present in the retained event ledger;
2. identify affected business keys;
3. append new evidence to the event ledger;
4. delete only affected history rows;
5. rebuild those keys deterministically from the complete retained event stream;
6. treat tombstones as history boundaries but not published versions;
7. publish `<ENTITY>_CURRENT` as a normal view over `is_current = true`.

This supports replay, delete/reinsert and late-arriving events without hiding behavior in a shared dbt materialization.
