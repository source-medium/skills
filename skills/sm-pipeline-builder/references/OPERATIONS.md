# Operations

A pipeline nobody watches is a pipeline that fails silently for months.
Operate every bespoke pipeline with the same four habits: classify errors,
schedule honestly, backfill deliberately, and keep the run log readable.

## 1. Classify every error into exactly three buckets

- **Retryable / transient**: rate limits with a reset window, 5xx, network
  blips, BigQuery slot contention. Retry with backoff, bounded attempts,
  then escalate — unbounded retry converts an outage into a bill.
- **Terminal**: bad credentials, revoked grants, missing required config,
  entitlement errors (the plan doesn't include the endpoint — no credential
  rotation can fix that), unparseable contract changes. Stop and page a
  human immediately; retrying terminal errors on a schedule is how one bad
  secret generates ten thousand error rows.
- **Deferrable**: source has no data yet for the window, dependency table
  not ready, provider maintenance window. Record the reason, skip the
  window without advancing the cursor, try next cadence.

One fault, one bucket, decided in code — not by whoever reads the log.
A stream-scoped failure on a best-effort stream must not disable the whole
pipeline when core streams still load; a denied payload-critical stream is
the exception that fails the run.

## 2. Failure streaks before alarms

A single failed run is information; a pattern is an incident.

- Alert on consecutive failures (streak ≥ 2–3 depending on cadence), not on
  any single failure. Transient provider blips are normal and self-heal.
- Auth-terminal failures alert on first occurrence — they never self-heal.
- A disabled pipeline stays visible: quality checks must distinguish
  "intentionally paused" from "stale and nobody noticed." Paused-with-reason
  is documentation; stale-without-reason is an incident.

## 3. Schedule for the source, not the clock

- The poll cadence is a polling interval, not a data interval. Poll at least
  as often as the source changes meaningfully; let cursor state decide
  whether there is work, and exit fast when there isn't.
- Expensive full pulls (snapshots, restatement windows, wide backfills)
  run on their own slower cadence inside the same pipeline — not on every tick.
- After the source's business-day close, pull the close capture forward:
  one prompt run after close beats six runs polling an open day. See
  `references/INCREMENTAL.md`.
- Provider quota deferrals (daily budgets, partition-modification limits)
  persist a cooldown and skip until it expires. A cooldown row is a schedule
  fact, not a failure — don't count it in the failure streak.

## 4. Backfill deliberately

- Every backfill declares: window start/end, reason, owner, and expected row
  order of magnitude. "Re-run it and see" is not a backfill plan.
- Windowed, checkpointed, resumable — per `references/INCREMENTAL.md`.
  Verify target-table coverage after, per `references/DATA_QUALITY.md`.
- Never run two backfills (or a backfill plus the incremental) over the same
  window concurrently unless the write pattern is pure idempotent MERGE.
- A backfill that fetched nothing is not complete — it is an incident
  report. Completion requires rows verified in the target.

## 5. Cost hygiene

- Dry-run backfill-verification queries; keep partition filters on every
  large-table read, including the monitoring queries themselves.
- Watch per-pipeline bytes scanned and slot usage monthly. A monitoring
  query that scans the whole fact table hourly costs more than the pipeline
  it watches — aggregate the check inputs (run log, coverage mart) instead.
- Dev and scratch datasets carry table expirations; audit quarterly and
  drop what no run has read.

## 6. Secrets and access

- Credentials live in a secret manager (or environment-injected secrets at
  runtime), never in code, never in chat, never in a spec file. The spec
  names the secret; only the runtime reads it.
- Least privilege per pipeline: write access to its own datasets, read
  access to SourceMedium datasets, nothing else. One shared god-credential
  turns one leak into a fleet incident.
- Log the credential identity (which secret, which grant), never the
  credential value. "Auth failed for grant X" is debuggable; a redacted
  blob is not.
