# Release operations

Release scripts are generated for review and explicit execution. `esf` never activates or rolls back a dataset by connecting to Snowflake.

Control migration `120_release_readiness.sql` adds the domain-local release evidence contract:

- `CONTROL.DATASET_VERSION_INVARIANT_V` checks active/candidate pointer consistency;
- `CONTROL.RELEASE_READINESS_V` summarizes candidate runtime, DQ and comparison evidence;
- `CONTROL.RELEASE_RUN` records each activate/rollback attempt and its failed phase;
- `CONTROL.RELEASE_RUN_LATEST_V` is the stable latest-attempt audit surface.

Typical flow:

```text
active v1
  -> scaffold-version v2
  -> deploy candidate SQL
  -> replay/bootstrap/refresh and catch up
  -> validate candidate after latest runtime evidence
  -> compare active vs candidate after latest runtime evidence
  -> release-sql v1 -> v2
  -> preflight.sql
  -> engineer reviews READY / REVIEW_REQUIRED / BLOCKED
  -> activate.sql repeats hard preflight
  -> cutover + postflight + RELEASE_RUN audit
  -> postflight.sql
```

`BLOCKED` is never bypassed. `REVIEW_REQUIRED` is not automatically converted to PASS; if the domain accepts review-only evidence, that acceptance must be explicit and reasoned in the generated release operation.

Candidate catch-up/refresh belongs before release preflight. The cutover must not create new candidate transformation evidence after DQ/comparison has already been accepted.

Keep the prior active version available through the approved rollback window. `rollback.sql` is fail-closed if another candidate has been registered since the cutover, so an old rollback bundle cannot silently override a newer release cycle.

Generated release directories are ownership units: if a target release directory already exists, the framework changes zero bytes.
