---
name: sm-pipeline-builder
description: >
  Use this skill when a technical operator wants to build or operate a bespoke
  data pipeline around SourceMedium data: custom source extracts, incremental
  loaders, backfills, bounded one-off repairs on customer-owned tables,
  customer-owned dbt models and marts (including marts that join the
  customer's own tables to SourceMedium tables), data-quality and freshness
  checks for those pipelines, and publishing customer-owned tables out of
  BigQuery into a system the operator owns. Writing dbt or DDL/DML over the
  customer's OWN tables is in scope. Pipelines run outside SourceMedium
  infrastructure (any scheduler, any loader) and write only to
  customer-owned destinations. Do not use for SELECT-only analysis (use
  sm-bigquery-analyst), dashboards (use sm-dashboard-builder), or work inside
  SourceMedium's own managed pipelines and dbt project — managed-connector
  incidents belong to SourceMedium support, not this skill.
metadata:
  author: sourcemedium
  version: "1.0"
  short-description: "Build bespoke BigQuery pipelines next to SourceMedium data."
  requirements: "Requires write access to customer-owned destinations (read-only on SourceMedium datasets); Python 3.9+ with PyYAML for helper scripts."
---

# SourceMedium Pipeline Builder

Help technical operators build bespoke data pipelines that live next to
SourceMedium data: extract from a custom source, land it in their own
BigQuery datasets, model it, validate it, and operate it. The patterns here
are distilled from years of production ETL and dbt experience — cursors that
don't lose data, merges that don't duplicate, money math that doesn't drift,
and checks that catch silent failures. Prefer deterministic scripts and
measured source behavior over guessing.

## Requirements

- BigQuery project access with **write** permission on customer-owned datasets
  (read on SourceMedium datasets; never write to `sm_*`)
- A scheduler you own (cron, Airflow, dbt Cloud, GitHub Actions, Cloud
  Scheduler — the skill is scheduler-agnostic)
- `python3` (3.9+) with PyYAML for `scripts/validate_pipeline_spec.py`
- `bq` CLI (or equivalent) for dry-runs and verification queries

## Workflow

1. **Write the spec first.** Copy the template to a per-pipeline file — do
   not edit the template in place — fill in source, grain, keys, windows, and
   quality checks, then validate **the copy**:
   ```bash
   cp assets/pipeline_spec_template.yaml specs/<pipeline>.yaml
   # edit specs/<pipeline>.yaml
   python scripts/validate_pipeline_spec.py specs/<pipeline>.yaml
   ```
   Validating the untouched template always passes and proves nothing.
   Re-run the validator with `--strict` before go-live.
2. **Probe the source live** with a bounded sample before designing around
   it (`references/PIPELINE_DESIGN.md`). Docs describe intent; responses
   describe behavior.
3. **Land raw, then model.** Immutable raw landing first, typed clean layer,
   business marts last. Marts never read raw directly.
4. **Load incrementally** with cursor plus overlap and idempotent merges
   (`references/INCREMENTAL.md`, `references/BIGQUERY_PATTERNS.md`).
5. **Validate on the ladder**: canary, sample backfill with source parity,
   full history on grain/key/money changes, then incremental
   (`references/DATA_QUALITY.md`).
6. **Operate it**: error buckets, failure streaks, deliberate backfills,
   cost hygiene (`references/OPERATIONS.md`).
7. **Integrate cleanly** with SourceMedium data: read `sm_*`, write your
   own, join on verified keys with validity flags
   (`references/SM_INTEGRATION.md`).
8. **Hand over the readiness checklist** (`assets/readiness_checklist.md`)
   with every item evidenced, not asserted.

## Reference Routing

Read only what the task needs:

- `references/PIPELINE_DESIGN.md` — source assessment, ELT layering, dataset
  layout, first-build sizing, publishing out of the warehouse.
- `references/INCREMENTAL.md` — the three load modes and when each is
  correct, cursors, overlap, restatement, idempotent MERGE, business-day
  close, backfill resumes.
- `references/BIGQUERY_PATTERNS.md` — batch loads, partitioning/clustering,
  money/NUMERIC, schema discipline, load metadata.
- `references/DATA_QUALITY.md` — coverage checks, table tests, validation
  ladder, check failure semantics.
- `references/OPERATIONS.md` — error buckets, streaks, scheduling, backfill
  discipline, cost, secrets.
- `references/SM_INTEGRATION.md` — the read/write boundary with SourceMedium
  datasets, join keys, validity flags, metric canonicity, freshness inputs.

If the task also needs warehouse discovery or SELECT-only analysis, use the
`sm-bigquery-analyst` skill if installed. If it needs dashboards over the
finished tables, use `sm-dashboard-builder` if installed.

One-off customer-owned DDL/DML (a single bad window, one added column) is
bounded single-window pipeline work under this skill: write or amend the
spec, validate it, and follow the same ladder. It is not SELECT-only
analysis. Managed SourceMedium connector incidents are never in scope —
route those to SourceMedium support.

## Hard Rules

These are hard constraints. Do not bypass.

1. **Spec before code.** No extract, model, or backfill without a validated
   pipeline spec naming grain, primary key, cursor, overlap, bounded
   bootstrap window, deletes behavior, auth failure mode, and checks. The
   validator enforces the structural half at any time and the declaration
   half under `--strict`; run `--strict` before the first production write,
   not just before go-live.
2. **Never write to `sm_*` datasets.** Bespoke tables live in customer-owned
   datasets. No exceptions, no "temporary" exceptions.
3. **Resolve the write target before the first write; never infer it.**
   Read the active project from the environment (`gcloud config get-value
   project` or equivalent) and confirm the destination project and dataset
   against the spec. Treat any project or dataset that differs from the
   resolved one — including a similarly-named tenant — as untrusted, and
   stop. Dev and production destinations are named explicitly in the spec;
   a pipeline that cannot tell which one it is pointed at does not run.
4. **Never advance a cursor past unwritten data.** Truncated, capped, or
   failed runs resume from the old position. A zero-row "success" is a
   failed run until proven structurally empty.
5. **Every load is idempotent.** MERGE on a stable key or windowed
   DELETE + INSERT on identical windows. Re-running any window any number
   of times yields the same table. One writer per window: serialize
   concurrent backfills and incrementals over the same window with a lease,
   a scheduler singleton, or a state store — concurrent DELETE + INSERT
   destroys data.
6. **NULL keys never merge.** Any nullable grain column forces a deterministic
   surrogate key (`SHA256` over the grain, declared as `surrogate_key` in the
   spec). Test PK uniqueness and not-null on a schedule.
7. **Money is DECIMAL via strings, quantized before load.** No float
   intermediates, units declared in the spec, ratios stay FLOAT64.
8. **Grain changes are rebuilds.** Adding or removing a dimension means a new
   table plus a full re-walk — never an in-place evolution, never a silent one.
9. **Measure the source; don't trust the docs.** Pagination stop conditions,
   money units, history limits, restatement horizons, and timezone closes are
   proven with live probes and recorded in the spec.
10. **Coverage over status.** Bootstrap and backfill completion require rows
    verified in the target, per-window. Exit code zero is not evidence.
    Dry-run verification and backfill reads first and enforce a bytes cap
    (`--maximum_bytes_billed` or equivalent); bound the first build to a
    small window, never all history.
11. **Bound the write side, not just the read side.** Every backfill campaign
    declares a ceiling before it starts — maximum windows per run and a bytes
    or cost budget, both recorded in the spec's `cost` block. On breach, stop
    and report progress; never widen the ceiling mid-campaign without saying
    so. A read cap alone does not stop a backfill loop from spending.
12. **No fabricated data, ever.** If a check cannot run, report the exact
    failure and stop that scope. If access fails, say which project/dataset
    failed and what grant is needed.
13. **Secrets stay secret.** Name them in the spec; only the runtime reads
    them. Never credentials in code, chat, logs, or specs.
14. **Destructive operations need explicit human confirmation.** State scope,
    effect, and rollback before running any of: `CREATE OR REPLACE TABLE`,
    `TRUNCATE TABLE`, a load job with `WRITE_TRUNCATE` / `bq load --replace`,
    window `DELETE`s, `DROP` of a table or dataset, production table
    rebuilds, and full-history re-walks. The first three overwrite a table
    without the word "delete" appearing anywhere — treat them as deletes.
15. **Minimize PII and privilege.** Strip credentials, tokens, and raw PII
    you have no license to store before the load leaves memory; declare PII
    columns in the spec and caveats, and declare them again on any egress to
    a system outside the warehouse. Grant each pipeline write access to its
    own destinations and read access to SourceMedium datasets — nothing else.

## Output Contract

For a new-pipeline job, always return:

1. **Spec** — the validated pipeline spec file (or a diff to it), including
   grain, keys, cursor/overlap, windows, close, and declared checks.
2. **Build** — load code / SQL / model definitions, with the layer each
   belongs to (raw, clean, mart) stated explicitly.
3. **Validation evidence** — canary results, source-parity sample totals,
   dry-run bytes for large queries, and which ladder rungs were run.
4. **Runbook** — schedule, error buckets, freshness expectation, backfill
   procedure, and the readiness checklist state.
5. **Caveats** — unmeasured source behaviors, structural emptiness claims,
   PII columns, and anything the next operator must know.

## Scripts

Run scripts from the skill directory. They are optional helpers; if the agent
environment cannot execute them, follow the same checks manually.

- `scripts/validate_pipeline_spec.py` — validates a pipeline spec file
  (YAML or JSON). Errors on: missing source/destination declarations;
  missing per-stream name, grain, or primary key; a primary key not
  derivable from the grain without a declared `surrogate_key`; an unknown
  `load.mode`; merge mode without a cursor or positive overlap;
  `append_restate` without `restatement_days` and `incremental.window_column`;
  a destination dataset under `sm_*`; and any value anywhere in the spec that
  looks like a live credential rather than a secret name. Exit 0 when valid,
  exit 2 with reasons when not — malformed files (bad YAML/JSON, a scalar
  where a mapping belongs, a missing file) exit 2 with a message, never a
  traceback. `--strict` promotes warnings (missing auth secret or failure
  mode, bootstrap window, deletes behavior, timezone close, undeclared money
  scale, no coverage check) to failures.
- `scripts/qa_sm_pipeline_skill.py` — package and spec-validator QA harness
  for this skill.
