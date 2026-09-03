# Pipeline Design

Design the pipeline on paper before writing code. Copy
`assets/pipeline_spec_template.yaml`, fill it in, and validate it with
`scripts/validate_pipeline_spec.py`. A pipeline with no written spec is a
pipeline whose grain, keys, and restatement behavior get rediscovered during
an incident.

## 1. Assess the source first

Answer these from live API responses, never from documentation alone. Vendor
docs describe the happy path; measure the real one with a bounded probe
(a handful of requests against a small window) before designing around it.

- **Auth shape**: static key, OAuth2 refresh, per-account compound credential?
  What fails when it expires, and who re-authenticates?
- **Pagination mechanics**: page numbers, opaque cursors, or full snapshots?
  What is the exact stop condition — empty page, short page, cursor that stops
  advancing? Prove it: one truncated sample is cheaper than a silent cut.
- **Rate limits**: requests per second, per minute, or a daily budget?
  A daily budget is a window-sizing input, not a backoff input.
- **Time axes**: which fields are event time, which are updated time, which are
  server receipt time? Cursor on updated time; window backfills on event time.
- **Restatement**: does the source rewrite history (attribution, finance,
  ad platforms)? Over what trailing horizon? No declared horizon means you
  pick one explicitly and re-pull it every run.
- **Deletes**: does the source hard-delete, and is there a tombstone or status
  flag? If deletions are invisible, say so in the spec — downstream must know.
- **Money**: units (micro-cents?), types (int/float/decimal string), scale.
  See `references/BIGQUERY_PATTERNS.md`.
- **Timezone**: in which zone does the source close a business day?
  See `references/INCREMENTAL.md`.

## 2. Choose ELT over ETL

Land raw source payloads first, transform in the warehouse after.

- The raw landing table is immutable and source-faithful: one row per source
  record, nested structures kept as JSON, no business logic at extract time.
  Reconstructing history you transformed away is impossible; re-running a
  transform over raw history is routine.
- Name the landing dataset so its rawness is obvious (for example
  `<domain>_raw` or `<domain>_landing`), separate from clean modeled tables.
- Keep every source field you receive, even ones with no consumer today.
  Dropping a field is a schema decision that needs the same review as adding one.
- Exception: strip credentials, tokens, and raw PII you have no license to
  store before the load leaves memory. PII minimization happens at extract,
  not in a later cleanup ticket.

## 3. Layer the warehouse side

Three layers, each with one job:

1. **Landing** (`<source>__<entity>_raw`): byte-faithful, append-only,
   plus load columns (`_synced_at`, `_source`, `_run_id`). No dedup, no joins.
2. **Clean / staging** (`stg_<entity>`): typed, renamed, filtered to the
   grain you declared. One row per primary key. This is where JSON is
   unpacked, money is scaled, and timezones are normalized — once, in one place.
   If you adopt dbt, bridge models between staging and marts use the `int_`
   prefix per SourceMedium reporting conventions.
3. **Marts** (`fct_` / `dim_` / `rpt_`): business logic, joins to
   SourceMedium tables, metric definitions. Marts read clean tables, never raw.
   SourceMedium's own warehouse additionally ships `obt_` one-big-table models
   for BI — read them as inputs; don't reuse the prefix for bespoke tables
   unless your team adopts it deliberately.

A consumer asking "where did this number come from" should walk exactly two
hops: mart to clean, clean to raw.

## 4. Decide the dataset layout up front

- Write bespoke tables to **your own datasets**, never into SourceMedium
  datasets. See `references/SM_INTEGRATION.md`.
- One dataset per concern beats one dataset per pipeline: raw, clean, and
  marts stay separately addressable for IAM, retention, and cost attribution.
- Partition by business date, cluster by the entity you filter on
  (tenant/store, then id). Decide this before the first load — repartitioning
  a large table later is a rebuild.
- Give every dataset a default table expiration for scratch/dev copies, and
  label datasets with `owner` and `purpose` so a stranger can tell what is
  safe to delete.

## 5. Size the first build

- Backfill one bounded historical window first (7–30 days, or one natural
  business cycle), validate it end to end, then widen. Never open with "all
  history."
- Declare the bootstrap window in the spec. "Backfill everything the API
  allows" is not a window — APIs have undocumented history limits, and an
  unbounded first run discovers them at maximum cost.
- If the source has a documented history limit, record it as terminal:
  windows older than the limit are permanently empty, not retryable gaps.

## 6. Publishing out of the warehouse

Some bespoke pipelines run the other direction: read customer-owned tables
(and SourceMedium tables) and publish into a system the operator owns — a
Snowflake or Postgres instance, an object store, a vendor API, a reverse-ETL
destination. Declare it with `destination.kind: external` plus `system` and
`pii`, and the same doctrine applies with three additions.

- **Idempotency is now the far end's problem, and it is still your problem.**
  You no longer control the write semantics, so state them: does the target
  upsert on your key, append blindly, or replace a partition? An append-only
  target plus a re-pulled restatement window duplicates every restated row.
  Pick a target-side key and prove a rerun of one window is a no-op before
  scheduling anything.
- **Egress makes PII a licensing question, not just a storage question.**
  Data you are allowed to hold in the warehouse may not be data you are
  allowed to send onward. Enumerate the columns crossing the boundary in
  `destination.pii` — `none` is a valid, and reviewable, answer. The
  validator requires the field for external destinations precisely so the
  question gets asked once, in writing, rather than discovered in an audit.
- **Do not let a SourceMedium metric change meaning on the way out.** A
  metric published under a SourceMedium name must be the SourceMedium
  definition, filters and all (`references/SM_INTEGRATION.md`). If the
  downstream system needs a different cut, it gets a different name. The
  most common way a bespoke export causes an incident is a column called
  `net_revenue` in a second system that quietly does not match the first.

Freshness and coverage checks still cover your side of the boundary: assert
what left the warehouse, and gate on the source table's publish date rather
than on the export job's exit code.
