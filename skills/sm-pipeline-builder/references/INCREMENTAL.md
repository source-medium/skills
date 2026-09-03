# Incremental Loading

The incremental contract: every run loads exactly the new and changed source
records, resumes exactly where the last successful run stopped, and never
advances its position past data it has not durably written.

## 1. Choose the load mode

Every stream declares exactly one `load.mode`. The mode decides the write
pattern, and picking the wrong one is not a performance problem — it is a
correctness problem that shows up as duplicate or immortal rows months later.

| `load.mode` | Write pattern | Use when | Also required in the spec |
|---|---|---|---|
| `snapshot` | Replace the table each run | The source only exposes current state, and the whole set is small enough to refetch on the cadence | Nothing extra — but say so in `deletes`: a snapshot silently forgets deleted rows |
| `merge` | `MERGE` on the primary key | Records are appended and updated in place, and a record that once existed keeps existing | `incremental.cursor_field`, `incremental.overlap` |
| `append_restate` | `DELETE` the window, re-`INSERT` it | The provider recomputes a window, and rows can both change **and disappear** | `restatement_days`, `incremental.window_column` |

The dividing line between `merge` and `append_restate` is whether rows can
vanish. `MERGE` has no way to express "and delete anything I did not send
this time" without a full-window anti-join, so a vanished row survives
forever and quietly inflates every total built on it. Provider-computed
aggregates — ad platform daily rollups, attribution tables, finance feeds —
regroup their own rows and drop empties, which is exactly that case.

`append_restate` is only safe when the fetch window and the delete window are
the same window, which is why `incremental.window_column` is required: it
names the column both halves target. Fetching wider than you delete appends
duplicates; deleting wider than you fetch destroys rows the run then refuses
to rewrite.

## 2. Cursor plus overlap

- Cursor on the source's **updated time**, not event time. Event-time cursors
  permanently lose late-arriving corrections; an order restated weeks later
  has a new updated time but an old event time.
- Subtract an **overlap** from the stored cursor every run (24–72h is a sane
  default) and merge idempotently, so records updated mid-run are re-fetched
  instead of skipped.
- Persist the cursor only after the load succeeds. A run that extracts but
  fails to write must resume from the old cursor, not the new high-water mark.
- A run that loads zero rows because it was truncated (row caps, timeouts,
  budgets) must NOT advance the cursor. Truncation without resume is silent
  data loss wearing a success status.
- With no state store, derive the floor from the destination itself
  (`MAX(cursor) - overlap`) on each run. With a state store, keep one row
  per (pipeline, stream): last cursor, last run id, last row count.

## 3. Restatement windows

Any source that recomputes history — ad platforms, attribution vendors,
finance feeds — needs a trailing re-pull window, not just a cursor.

- Declare `restatement_days` per stream from measurement (7, 14, 30 — match
  the source's actual revision horizon, not a guess).
- On `merge` streams, re-extract the trailing window and MERGE: changed rows
  update, and the merge key must still match them.
- On `append_restate` streams, the trailing window is re-pulled and the
  window is DELETEd and re-INSERTed rather than merged, for the reason in
  §1: vanished rows are the point. `restatement_days` sets how far back the
  re-pull reaches; `incremental.window_column` names the column the DELETE
  targets.

## 4. Idempotent writes

- Every table has a stable primary key declared in the spec, and every load
  is a MERGE (or windowed DELETE + INSERT) on that key. Re-running any window
  any number of times produces the same table.
- BigQuery MERGE never matches NULL keys: a nullable column in the merge key
  re-inserts every NULL-bearing row on every run and reads as permanent
  duplication. When any grain column is nullable, merge on a deterministic
  surrogate instead — `SHA256` over the grain tuple, joined with an
  unambiguous delimiter with NULLs encoded explicitly (never bare
  concatenation: `('a','bc')` and `('ab','c')` collide under `a || b`; use a
  unit separator with `COALESCE(col, '<NULL>')` or equivalent) — and keep
  the raw columns alongside, source-faithful. In BigQuery `SHA256()` returns
  BYTES, so store `TO_HEX(SHA256(...))` or an equivalent string encoding.
  Declare it in the spec as `surrogate_key` (`name` plus the `from` columns
  it hashes) so the key and the grain stay provably tied to each other.
- The merge key moves with the grain. Adding or removing a dimension from an
  aggregate changes what a row means: that is a table rebuild plus a full
  re-walk of history, never an in-place schema evolution. Adding a metric
  column is evolution; changing the grain is a rebuild.
- Co-emitted child rows (line items fanned out from one parent walk) share
  the parent run: a child must never be emitted without its parent landing
  in the same run, or orphans accumulate.

## 5. Business-day close

A provider-computed daily aggregate is not complete at midnight UTC. Each
source closes its business day in its own zone — often the advertiser's or
store's local timezone — and rows for "today" keep arriving until that close.

- Declare the close per stream: fixed offset or a timezone column resolved
  at extract time. Never store a numeric offset when a zone name exists —
  offsets go stale across daylight saving.
- Clip routine extracts to the last fully closed date. Do not write the
  still-open day; it will restate.
- Gate downstream consumers on the newest closed-and-loaded date, not on row
  presence. Rows appear as soon as the first pull touches a date — presence
  is evidence of extraction, not of completeness.
- A complete "yesterday" read at 1am local time is physically impossible for
  sources closing in western zones. If stakeholders expect early-morning
  freshness, say so in the spec instead of letting them infer it from
  partial rows.

## 6. Backfills and resumes

- Backfills run in bounded, checkpointed windows (days to weeks per chunk,
  sized to the source's rate limits). Each completed window checkpoints
  before the next starts, so an interrupted backfill resumes at the first
  un-checkpointed window instead of restarting.
- A partial window or a capped canary run must never record the campaign
  complete. Completion is claimed only when every window in the declared
  range has checkpointed with rows verified — check `records_loaded`, never
  the exit status alone.
- Keep one owner per (pipeline, window): two concurrent writers on the same
  window plus MERGE is merely wasteful, but concurrent writers plus
  DELETE + INSERT is destructive. Serialize with a lease, a scheduler
  singleton, or a state store — pick one and use it everywhere.
- Scope changes invalidate history: if the extracted scope (accounts,
  stores, streams) changes mid-campaign, re-walk the affected windows.
  A completion stamp names a scope; a new scope needs new evidence.
