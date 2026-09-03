# Pipeline Readiness Checklist

Copy this checklist per pipeline. Every item needs evidence (a command, a
row count, a link), not an assertion. Nothing goes live with an unchecked
box unless the exception is written down with an owner and a date.

## Spec

- [ ] Spec file validates clean: `validate_pipeline_spec.py <spec> --strict`
  (the per-pipeline copy, not the untouched template)
- [ ] Grain, primary key, cursor, overlap, bounded bootstrap window, deletes
  behavior per stream, and auth failure mode are declared per spec
- [ ] Source behaviors recorded from live probes (pagination stop, money
  units, history limit, restatement horizon, timezone close) — no "per docs"
  entries without a probe note
- [ ] Credential is a secret name, not a value, and least-privilege access
  is confirmed
- [ ] Destination project and dataset resolved from the live environment and
  matched against the spec; dev and production targets named separately
- [ ] Backfill ceiling declared in the spec `cost` block (max windows per
  run, bytes/cost budget) and the breach behavior is stop-and-report
- [ ] PII columns declared in spec; extract strips credentials, tokens, and
  unlicensed PII before load

## Build

- [ ] Raw landing is append-only and source-faithful (nested bags kept as JSON)
- [ ] Clean layer types, renames, and unpacks in exactly one place per entity
- [ ] Marts read clean tables only, never raw
- [ ] Loads are idempotent: MERGE on stable keys, or windowed DELETE + INSERT
  on identical windows; rerun of any window verified byte-identical
- [ ] One writer per window enforced (lease, scheduler singleton, or state
  store); concurrent backfill plus incremental over one window never allowed
- [ ] Nullable grain columns use a surrogate key; PK uniqueness + not-null
  tests exist and pass
- [ ] Money is decimal-via-string, quantized pre-load; units recorded in spec
- [ ] Partitioning (business date) and clustering (tenant/entity) set before
  first production load
- [ ] Every row carries `_synced_at`, `_source`, `_run_id`; run-log table exists

## Validate

- [ ] First build bounded to a small window first, never all history
- [ ] Canary run verified on target rows + run log, not just exit code
- [ ] Sample backfill reconciled to source totals (3–5 entities, recent window)
- [ ] Full-history rebuild diffed on grain/key/money changes; every delta explained
- [ ] Incremental run twice: second run loads only the overlap window
- [ ] Dry-run bytes reviewed for backfill-verification queries; bytes cap set

## Operate

- [ ] Schedule owns the cadence; close-capture run scheduled after source close
- [ ] Errors classified (retryable / terminal / deferrable) in code
- [ ] Freshness + coverage checks scheduled with per-stream expectations
- [ ] Failure-streak alerting configured; auth-terminal alerts on first occurrence
- [ ] Backfill procedure documented (window, owner, resume point, verify step)
- [ ] Every overwrite path has explicit human confirmation with scope,
  effect, and rollback: `CREATE OR REPLACE TABLE`, `TRUNCATE`, load jobs with
  `WRITE_TRUNCATE` / `--replace`, window `DELETE`s, `DROP`s, production
  rebuilds, and full-history re-walks
- [ ] Backfill chunk size checked against the partition-modification quota
  for the target table
- [ ] Scratch/dev datasets carry expirations; cost of monitoring queries reviewed

## Integrate (when joining SourceMedium data)

- [ ] Reads `sm_*` datasets only; writes to customer-owned datasets only
- [ ] Joins use verified keys with cardinality checked; customer side
  pre-aggregated unless 1:1 proven
- [ ] `is_order_sm_valid = TRUE` (or the relevant validity flag) applied
- [ ] Metric names resolved via the semantic catalog, not guessed columns
- [ ] Freshness gated on SourceMedium's publish date, not assumed partitions
- [ ] Order joins use the source-platform `order_id` scoped by `sm_store_id`,
  never SourceMedium's internal `sm_order_key`

## Publish (when writing outside the warehouse)

- [ ] `destination.kind: external` with `system` and `pii` declared
- [ ] Target-side write semantics stated (upsert key / append / replace) and
  a single-window rerun proven to be a no-op
- [ ] No SourceMedium metric name published with a non-SourceMedium definition
