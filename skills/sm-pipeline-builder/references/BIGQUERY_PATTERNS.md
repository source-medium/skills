# BigQuery Load Patterns

BigQuery rewards batch loads into partitioned tables and punishes cleverness
at write time. Default to the boring path below; deviate only with a measured
reason written into the pipeline spec.

## 1. Batch loads over streaming

- Use batch load jobs (`load_table_from_json`, `load_table_from_file`, or
  SQL DML) for pipeline writes. Reserve the streaming API for genuinely
  sub-minute latency requirements.
- Know which streaming path you are on, because the DML restriction is not
  uniform. Rows written by the legacy streaming API (`tabledata.insertAll`)
  or by the **Storage Write API over REST** cannot be touched by `UPDATE`,
  `DELETE`, `MERGE`, or `TRUNCATE` for **30 minutes** after the write, so a
  snapshot pattern (DELETE + INSERT) or a follow-up MERGE fails against
  freshly streamed rows. Rows written by the **Storage Write API over gRPC**
  can be modified by DML immediately — on that path this argument does not
  apply, and "use batch because of the buffer" is simply wrong.
- Two other streaming delays are often confused with the DML restriction and
  are not it: recently streamed rows may be unavailable to **table copy**,
  and `_PARTITIONTIME` on an ingestion-time partitioned table may stay NULL,
  each typically for a few minutes and **in rare cases up to 90**. If a
  backfill's copy step or partition pruning misbehaves right after a stream,
  this is why — not the 30-minute DML window.
- Prefer batch loads anyway, for reasons that survive every path above: a
  load job commits atomically, so one window is one addressable unit that
  either landed or didn't; batch loading is free where streaming is billed
  per byte; and there is no buffer state to reason about during a rerun.
- Extract to object storage (GCS) and load from there when payloads are
  large or pagination is slow: the extract can retry without re-hitting the
  source, and the load step stays a single atomic job.

## 2. Partition and cluster before the first load

- Partition by the business date column consumers filter on
  (`DATE(event_time)`, `report_date`). Partitioning is what makes
  dry-runnable, cost-capped queries possible — and what makes backfill
  windows cheap to rewrite.
- Cluster by the next most-filtered columns: tenant or store id first, then
  entity id. One dataset scan shared across tenants stays affordable only
  when the tenant predicate prunes.
- Require partition filters on the large tables (`require_partition_filter`)
  once consumers exist, so an unbounded query fails fast instead of billing.
  A query with no predicate on the partitioning column then fails with
  "Cannot query over table ... without a filter that can be used for
  partition elimination" rather than scanning everything. On ingestion-time
  partitioned tables the filter must be on `_PARTITIONDATE` /
  `_PARTITIONTIME`; on column-partitioned tables, on the partitioning column
  itself. The requirement propagates to views over the table.
- **Budget your partition modifications.** BigQuery caps how many partitions
  a single table can have modified per day, counted across load jobs, copy
  jobs, query jobs writing to a partition, and DML. A windowed
  DELETE + INSERT backfill touches partitions on both halves of every
  window, so a wide day-grained campaign is the pattern most likely to hit
  this — mid-campaign, after some windows have already landed. Size backfill
  chunks against the current limit on the quotas page
  (https://cloud.google.com/bigquery/quotas — the number changes, so read it
  rather than trusting a figure written here), spread a large re-walk across
  days, and treat the quota error as a deferrable fault with a cooldown
  (`references/OPERATIONS.md`), never as a failed window to retry immediately.

## 3. Money and numbers

Money bugs are silent and always in the same three places:

1. **Float intermediates.** Parse wire money through strings into decimals,
   never through float64.

   Be precise about why, because the usual folklore example does not
   reproduce. `CAST(CAST(30.4 AS FLOAT64) AS NUMERIC)` is exactly `30.4`,
   and even summing `0.1` a thousand times in FLOAT64 casts back to exactly
   `100`: `NUMERIC`'s 9 fractional digits absorb the binary error at
   ordinary money magnitudes. If you test the folklore claim you will find
   it false, and conclude wrongly that floats are fine.

   Two failures are real and both are silent:

   - **Rounding on a float intermediate lands on the wrong side.**
     `ROUND(2.675, 2)` is `2.67` in FLOAT64 and `2.68` in `NUMERIC`,
     because `2.675` is stored just under the true value. Every half-cent
     boundary in the dataset is a coin flip decided by binary representation.
   - **Magnitudes past ~15 significant digits lose precision before the
     cast can help.** `12345678901234567.89` through FLOAT64 arrives as
     `12345678901234568`. Micro-cent and milli-unit denominations reach this
     range faster than dollar amounts do.

   So: decode to a decimal type at the source mapping, quantize to the
   declared scale there, and let nothing in between be a float.
2. **Undeclared units.** Micro-cents, milli-units, and "amounts" with no
   documented denomination are all live possibilities. Scale at the source
   mapping, in one shared helper, with the unit recorded in the spec.
   Ratios (ROAS, rates) stay FLOAT64; attributed fractional conversions
   stay FLOAT64; currency amounts are NUMERIC.
3. **Mixed types on the wire.** JSON numbers that arrive sometimes-int,
   sometimes-float must be normalized before load or the schema flaps.

## 4. Schema discipline

- Land nested structures as JSON strings on the raw table; unpack into
  typed columns in the clean layer. Dynamic provider keys (per-platform
  maps, custom attributes) stay JSON forever — one new vendor key must not
  add one new column.
- New nullable column: evolution, safe. New REQUIRED column on a loaded
  table: every historical row violates it — backfill it or keep it NULLABLE.
- Grain change (add/remove a dimension): rebuild, per
  `references/INCREMENTAL.md`. Schema compatibility checks at load time
  catch the accident; they do not bless the change.
- Never let the loader infer schema from a sample in production. Declare
  the schema (or let the clean-layer SQL declare it) and fail the load on
  mismatch. An inferred schema is a silent contract renegotiation.

## 5. Query-side cost guardrails

- Dry-run every new query before executing it; enforce
  `--maximum_bytes_billed` (or the API equivalent) on exploratory and
  backfill-verification queries.
- Bound all exploratory reads with date/partition filters and `LIMIT`.
- Validate a backfill window's cost on one window before launching fifty:
  bytes scanned scale linearly, and the estimate is printed before you pay.

## 6. Load metadata on every row

Every loaded row carries, at minimum:

- `_synced_at` (TIMESTAMP, UTC): when this row was written.
- `_source`: which pipeline/stream wrote it.
- `_run_id`: which execution wrote it.

Plus one append-only run-log table per pipeline: run id, window start/end,
rows extracted, rows loaded, cursor before/after, outcome. When something
looks wrong six months from now, this table — not the scheduler UI — is the
evidence.
