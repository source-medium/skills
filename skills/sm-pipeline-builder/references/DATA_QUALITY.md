# Data Quality

A green scheduler proves runs happened. It proves nothing about the data.
Every pipeline ships with the checks below, running on a schedule, with
failures routed to a human — not just a log.

## 1. Coverage checks beat status checks

"Job succeeded" with zero rows loaded is the most common silent failure.
Assert on the data, not the exit code:

- **Row-count floor per window**: every load asserts `rows_loaded > 0`
  unless the source provably had no data (and "provably" means a source-side
  signal, not an empty response you chose to trust).
- **Business-date coverage**: for each date-grained table, which business
  dates have rows? A date island with no rows inside the declared history
  window is a gap until proven structurally empty (source history limit,
  account created later, stream opted in later). Record the proof beside
  the gap; unexplained islands re-fill.
- **Freshness per stream**: `MAX(event_time)` and `MAX(_synced_at)` per
  stream, compared against the declared cadence plus close lag. A slowly
  changing reference table and a dead event stream look identical without
  per-stream expectations — declare which streams may legitimately sit idle.
- **Source parity on samples**: after bootstrap and after any logic change,
  reconcile totals (spend, revenue, counts) between the warehouse and the
  source UI/API for a 3–5 entity sample over a recent window. Totals must
  match exactly; investigate every delta before calling the pipeline correct.

## 2. Correctness tests on the tables

Run these as scheduled tests (dbt tests, scheduled queries, or CI — the
mechanism matters less than the cadence):

- **PK uniqueness**: `GROUP BY pk HAVING COUNT(*) > 1` returns nothing.
  Any surplus means an append landed where a merge belonged, or a NULL key
  defeated the merge (see `references/INCREMENTAL.md`).
- **PK not-null**: every merge-key column is populated on every row.
- **Parent-child integrity**: child rows reference existing parents
  (line items to orders, events to entities). Orphan growth scan-over-scan
  means a walk stopped emitting one side.
- **Expected values**: one pinned query per core metric with a checked-in
  expected result over a frozen window. Metric refactors must move the
  expectation deliberately, never silently.
- **Validity flags**: test/cancelled/invalid rows are excluded from marts
  by an explicit flag (`is_*_valid`), and the flag's definition is tested,
  not assumed. When joining SourceMedium orders, that flag is
  `is_order_sm_valid = TRUE` — see `references/SM_INTEGRATION.md`.

## 3. The validation ladder for any change

1. **Canary**: bounded run (one entity, one small window, capped rows).
   Verify target rows, load metadata, and the run log — not just the exit code.
2. **Sample backfill**: one full business cycle; reconcile totals to source.
3. **Full history** (if the change touches grain, keys, or money): rebuild
   into a scratch table, diff row counts and metric totals against
   production, explain every delta. Apparent "data loss" is often a dedup
   fix — confirm which before shipping.
4. **Incremental**: run the daily path twice; the second run should load
   only the overlap window and change nothing else.
5. **Monitor**: freshness and coverage checks stay green for two full
   cadences before the change is called done.

Validate a modified incremental model full-refresh first, then incremental —
both runs, every time.

## 4. Failure semantics for checks

- A check failure names the exact table, window, and magnitude, and links
  the run-log rows. "DQ failed" with no scope is unactionable and will be
  ignored until the one time it matters.
- Distinguish actionable debt (rows that should exist and don't) from
  advisory evidence (structurally empty windows, source-deleted records).
  Advisory rows persist as documentation with a reason; only actionable
  debt pages.
- A check that fails on a known structural condition without naming it is
  a bad check — encode the condition (history limit, late opt-in, deleted
  at source) so the next reader doesn't re-investigate.
