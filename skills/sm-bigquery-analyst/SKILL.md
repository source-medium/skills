---
name: sm-bigquery-analyst
description: >
  Use this skill when an operator wants to analyze SourceMedium-hosted BigQuery
  data, verify BigQuery access, discover available SourceMedium tables or semantic
  metrics, generate safe SELECT-only SQL, produce auditable SQL receipts, or join
  their own warehouse tables to SourceMedium data. Works alongside the SourceMedium
  MCP server when it is connected. Do not use for DDL, DML, infrastructure
  provisioning, dbt authoring, or cross-tenant joins.
metadata:
  author: sourcemedium
  version: "2.0"
  short-description: "Analyze SourceMedium BigQuery safely."
  requirements: "Works on every SourceMedium plan through the SourceMedium MCP. The bq scripts need direct warehouse access (Pro) plus gcloud, bq, and network access to BigQuery."
---

# SourceMedium BigQuery Analyst

Help operators answer questions from SourceMedium warehouse data, from access
checks to an auditable answer. Prefer deterministic checks and SourceMedium's own
metric definitions over guessing. Never fabricate data when access, metadata, or
a query fails.

## Choose the Route

Two ways reach SourceMedium data, and the plan decides which the user has:

- **Through SourceMedium, on every plan**: the SourceMedium MCP server (tools
  named `get_data_context`, `search_data_catalog`, `describe_table`,
  `describe_tables`, `query_metrics`, `run_bigquery_sql`, `get_account_health`),
  signed in with the user's SourceMedium account.
- **Direct warehouse access, on Pro**: the user's own Google account (or their
  service accounts) querying BigQuery on their dedicated warehouse with `bq`,
  through this skill's scripts.

Use the MCP first whenever it is connected:

1. `get_data_context` first. It reports the warehouse project, the dataset names,
   and `allowed_datasets`.
2. Named SourceMedium metrics: `search_data_catalog`, then `query_metrics`. Its
   result includes the compiled SQL; use that as the SQL receipt. Do not hand-roll
   a catalog metric that `query_metrics` accepts. Today it refuses the new- and
   repeat-customer metrics (see `references/ANALYSIS_SEMANTICS.md`).
3. Custom SQL over SourceMedium datasets: `run_bigquery_sql`. On a dedicated
   warehouse it also reaches the customer's own datasets in the same project
   and region, for direct workspace members, within about 15 minutes of a
   dataset's creation. Its receipt carries a hash of the SQL, so keep the SQL
   you sent.
4. Stale data, missing sources, or "is my data flowing?": `get_account_health`.

With direct warehouse access, use this skill's `bq` scripts for what the MCP
cannot reach or do:

- The MCP is not connected.
- Tables outside `allowed_datasets`: `sm_sources`, or tables in another project
  of the customer's.
- A result that genuinely needs more than the MCP's limits (500 rows, a
  256 KiB response, 10 GiB scanned, 60 seconds). Pre-aggregate first; most
  questions fit.

Without direct warehouse access (Foundation plans, and agency access), the MCP
is the only route. Joining the customer's own tables to SourceMedium data in
the warehouse, `sm_sources`, and bulk extracts are not available; say so
rather than reaching for `bq`. A store- or brand-scoped grant also refuses
`run_bigquery_sql`: answer with `query_metrics` and say what it cannot cover.

Both routes follow every rule below. A CLI number for a catalog metric that
disagrees with `query_metrics` means the CLI SQL is wrong.

## Resolve the Warehouse Names

SourceMedium warehouses come in two layouts, and SQL needs the real names.

| | Dedicated warehouse (Pro) | Shared warehouse (Foundation) |
|---|---|---|
| Project | The tenant's own project, usually `sm-<something>`. Not always `sm-<tenant id>`. | `sourcemedium-bi` |
| Datasets | `sm_transformed_v2`, `sm_metadata`, `sm_views`, `sm_experimental`, `sm_utils`, `sm_sources` | `<tenant>_sm_transformed_v2`, `<tenant>_sm_metadata`, `<tenant>_sm_views`, `<tenant>_sm_experimental`, and `sm_utils` |
| Queried by | The MCP, or the user's own Google account | The MCP |
| The customer's own tables | Datasets that workspace editors and admins create in the same project | Not joinable with SourceMedium data in the warehouse |

Every example in this skill writes lane-neutral names:
`` `<project>.<sm_transformed_v2>.obt_orders` ``. Substitute the names
`get_data_context` reports. With direct warehouse access, the doctor resolves
and prints them too:

```bash
python scripts/sm_bq_doctor.py --project <project>
```

## Workflow

1. **Choose the route and resolve the warehouse** (above).
2. **Discover before SQL**: tables and freshness from `<sm_metadata>.dim_data_dictionary`,
   metric definitions from `<sm_metadata>.dim_semantic_metric_catalog`, actual
   store ids and categorical values with `SELECT DISTINCT`.
3. **Resolve the metric**: catalog definition, filters included
   (`references/ANALYSIS_SEMANTICS.md`).
4. **Write safe SQL**: Standard SQL, fully qualified tables, SELECT/WITH only,
   bounded dates, aggregate before dividing.
5. **Dry-run and execute under a cost cap**: the MCP tools apply theirs; with
   direct access, `scripts/sm_bq_query.py`.
6. **Validate the result shape** before concluding (below).
7. **Return the output contract** (below).

## Discovery

Through the MCP: `get_data_context`, `search_data_catalog`, and
`describe_table(s)`, plus `run_bigquery_sql` for the queries in
`references/QUERY_PATTERNS.md`. With direct warehouse access, the discovery
script does the same:

```bash
python scripts/sm_bq_discover.py --project <project> --tables --metrics
python scripts/sm_bq_discover.py --project <project> --metrics --metric-search revenue
python scripts/sm_bq_discover.py --project <project> --categorical "<sm_transformed_v2>.obt_orders.sm_channel" \
  --days 90 --date-column order_processed_at_local_datetime
```

Every discovery query runs under a bytes cap and says when it hit its row limit.

Read only the reference files the task needs:

- `references/SCHEMA.md`: warehouse layouts, datasets, tables, grains, keys, columns.
- `references/ANALYSIS_SEMANTICS.md`: metric resolution, revenue, new customers,
  channels, subscriptions, marketing, cohort LTV, and data-health rules.
- `references/QUERY_PATTERNS.md`: copy/paste SQL for discovery and common questions.
- `references/CUSTOM_DATA.md`: documenting and safely joining customer-owned tables.
- `references/TROUBLESHOOTING.md`: access, auth, permission, query, and cost failures.

## Safety Rules

These are hard constraints. Do not bypass.

1. **SELECT-only.** No INSERT, UPDATE, DELETE, MERGE, CREATE, DROP, EXPORT, COPY,
   or scripting. `scripts/sm_bq_query.py` checks the text and then BigQuery's own
   parse of the statement type.
2. **Dry-run first, then execute under a bytes cap** (default 1 GiB). Over the
   cap: tighten the query or ask before raising it. BigQuery bills the columns
   a query reads, so select only the columns you need.
3. **Bound every query**: a date filter on any table with history, and a `LIMIT`
   on exploratory reads. A result that hits the row limit is incomplete: the
   query script exits 7 with status `truncated` rather than returning a silent
   partial answer.
4. **Cross-tenant isolation.** Use only the project and datasets resolved for
   this user. Never infer a project or dataset from a similar tenant name, and
   never join across tenants.
5. **No `SELECT *` for analysis.**
6. **Aggregates by default; PII only on request.** `obt_customers.customer_email`
   is plain text. Do not output email, phone, address, or name columns without
   explicit confirmation of scope and purpose; prefer hashing:
   `TO_HEX(SHA256(LOWER(TRIM(email))))`.

## Query Guardrails

1. Fully qualify tables: `` `<project>.<sm_transformed_v2>.obt_orders` ``.
2. Order analysis starts from `WHERE is_order_sm_valid = TRUE`.
3. Revenue is `order_net_revenue` unless the user asks for gross or total.
4. Ratios: aggregate first, then divide, `SAFE_DIVIDE(SUM(numerator), SUM(denominator))`.
   Averaging a per-row ratio is a different, incorrect number.
5. A catalog metric keeps its catalog filter. `calculation` is documentation, not
   runnable SQL; the filter is in `filter_condition`.
6. Dates: `*_local_datetime` columns are store-local DATETIMEs and are what
   SourceMedium reports on. Compare them through `DATE()`: a raw
   `<= DATE '2026-01-31'` silently drops everything after midnight on the 31st.
   UTC `*_at` TIMESTAMPs refuse a DATE comparison outright.
7. Enumerations (channel, source system, order type): discover values with
   `SELECT DISTINCT`, then match exactly. `LIKE`/`REGEXP` is for free text only.
8. Use `sm_store_id` (never `smcid`) and scope multi-store questions explicitly.
9. Cohort LTV: one `sm_order_line_type`, one `acquisition_order_filter_dimension`,
   and `sm_channel` either filtered or summed, never averaged.
10. Unknown tables or columns: read `INFORMATION_SCHEMA.COLUMNS` and sample values
    before writing SQL. Never guess names or filter constants.

## Query Result Validation

Before presenting a conclusion:

1. **Zero rows**: check `table_last_data_date` against the date range, the store
   filter against real `sm_store_id` values, and every filter constant against
   `SELECT DISTINCT` output.
2. **Inflated totals**: look for a missing grain filter (cohort table dimension,
   line type, or channel), or a join that fanned out.
3. **Suspiciously uniform or missing categories**: list the actual values before
   concluding a channel or source is absent.
4. **Ratio surprises**: recompute numerator and denominator separately.
5. **Metric ambiguity**: name the column or catalog metric used, and why.

## Output Contract

For analytical questions, always return:

1. **Answer**: a concise plain-English conclusion.
2. **SQL (copy/paste)**: the BigQuery Standard SQL behind the result, with the
   resolved project and datasets.
3. **Notes**: timeframe, metric definition (catalog name and filter), grain,
   store and channel scope, timezone, attribution lens.
4. **Receipt**: dry-run bytes, referenced tables, rows returned, and whether the
   result was truncated (from `scripts/sm_bq_query.py` or the MCP receipt).

If access or setup fails, do not fabricate results. Return the exact failing
step, the exact project and dataset, and the fix from
`assets/BIGQUERY_ACCESS_REQUEST_TEMPLATE.md`. Direct BigQuery access is part of
Pro and comes from membership in the customer's SourceMedium workspace, not from
their own GCP admin; without it, the MCP is the route.

## Scripts

Run scripts from the skill directory. They use the caller's own Google account,
so they need direct warehouse access (Pro). They are optional helpers; if the
agent cannot execute them, follow the same checks manually.

- `scripts/sm_bq_doctor.py`: CLI, auth, project, and access checks; resolves the
  warehouse layout and prints the dataset names to use.
- `scripts/sm_bq_discover.py`: tables, metrics (with filters), stores, schemas,
  and categorical values, every query capped.
- `scripts/sm_bq_query.py`: SELECT-only dry-run and capped execution. Rows go to
  stdout; the JSON receipt goes to stderr. Exit codes: 3 unsafe SQL, 4 dry-run
  failed, 5 over the bytes cap, 6 execution failed, 7 truncated.
- `scripts/sm_bq_common.py`: shared helpers the three scripts import.
- `scripts/qa_sm_bigquery_skill.py`: package and optional live QA for this skill.

## Hybrid Data (Your Tables + SourceMedium Data)

1. SourceMedium stays the source of truth for its metrics unless the user defines
   a custom metric from their own data, under a different name.
2. Read or create a project-local note such as `sourcemedium_custom_data.md` from
   the template in `references/CUSTOM_DATA.md` before writing hybrid SQL.
3. Check join-key cardinality on the customer side before any join; pre-aggregate
   unless it is provably 1:1. Fan-out silently inflates SourceMedium metrics.
4. Fully qualify both sides. Joins in the warehouse need direct warehouse access
   (Pro): the customer's datasets in the dedicated project, joined through
   `run_bigquery_sql` or `bq`, or another project of theirs through `bq`.
   Without it, join only the MCP's results with their data outside the
   warehouse, and say so.
5. Every rule above still applies: SELECT-only, cost cap, no raw PII.
