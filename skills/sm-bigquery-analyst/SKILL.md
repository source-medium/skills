---
name: sm-bigquery-analyst
description: >
  Use this skill when an operator wants to analyze SourceMedium-hosted BigQuery
  data, verify BigQuery access, discover available SourceMedium tables or semantic
  metrics, generate safe SELECT-only SQL, produce auditable SQL receipts, or join
  their own warehouse tables to SourceMedium data. Do not use for DDL, DML,
  infrastructure provisioning, dbt authoring, or cross-tenant joins.
metadata:
  author: sourcemedium
  version: "1.1"
  short-description: "Analyze SourceMedium BigQuery safely."
  requirements: "Requires gcloud, bq, and network access to BigQuery."
---

# SourceMedium BigQuery Analyst

Help operators work with SourceMedium BigQuery data from setup to analysis. Prefer deterministic CLI checks and scripts over guessing. Never fabricate data when access, metadata, or query execution fails.

## SourceMedium Warehouse Primer

SourceMedium hosts analytics-ready ecommerce warehouse data in BigQuery. A cold agent should treat the warehouse as discoverable, not memorized:

- `sm_metadata.dim_data_dictionary` tells you which tables exist, what they mean, whether they have data, and freshness.
- `sm_metadata.dim_semantic_metric_catalog` resolves metric names, labels, aliases, and calculations.
- `sm_transformed_v2` contains core modeled tables for orders, order lines, customers, ad performance, cohorts, events, and executive summaries.
- `sm_experimental` contains experimental attribution/MTA tables when enabled.
- Most tenant projects are named `sm-<tenant_id>`, but some hosted/shared layouts use custom dataset names. Use script dataset flags when defaults fail.

## Requirements

- `gcloud` CLI
- `bq` CLI
- Network access to BigQuery
- BigQuery permissions for the active SourceMedium project

## Workflow

1. **Verify setup first** with `scripts/sm_bq_doctor.py`.
2. **Discover reality before SQL** with SourceMedium metadata, `INFORMATION_SCHEMA`, and value-distribution queries.
3. **Choose the owning data source**:
   - SourceMedium metrics and dimensions: use `sm_metadata`, `sm_transformed_v2`, and when needed `sm_experimental`.
   - Customer-owned tables: read or create a project-local custom-data note before joining.
4. **Generate safe SQL**: Standard SQL, fully qualified tables, SELECT/WITH-only, bounded date filters, explicit metric definitions.
5. **Dry-run and execute with a cost cap** using `scripts/sm_bq_query.py` or equivalent `bq` commands.
6. **Validate result shape** before presenting conclusions.
7. **Return an auditable SQL receipt**.

## Setup Verification

Preferred:

```bash
python scripts/sm_bq_doctor.py --project sm-tenant-id
# If the warehouse uses tenant-prefixed datasets:
python scripts/sm_bq_doctor.py --project project-id --metadata-dataset tenant_sm_metadata --transformed-dataset tenant_sm_transformed_v2
```

If scripts are unavailable, run the equivalent manual checks:

```bash
gcloud --version
bq version
gcloud auth list
gcloud config get-value project
bq query --use_legacy_sql=false --dry_run 'SELECT 1 AS ok'
```

Then test SourceMedium metadata and one readable table in the active project. If any step fails, read `references/TROUBLESHOOTING.md` and use `assets/BIGQUERY_ACCESS_REQUEST_TEMPLATE.md`.

## Discovery

Before analytical SQL, discover available domains and freshness:

```bash
python scripts/sm_bq_discover.py --project sm-tenant-id --tables --metrics
# For focused metric discovery:
python scripts/sm_bq_discover.py --project sm-tenant-id --metrics --metric-search revenue
# If the warehouse uses tenant-prefixed datasets:
python scripts/sm_bq_discover.py --project project-id --metadata-dataset tenant_sm_metadata --transformed-dataset tenant_sm_transformed_v2 --tables --metrics
```

Read only the reference files needed for the task:

- `references/SCHEMA.md` — SourceMedium datasets, key tables, column conventions, and docs links.
- `references/ANALYSIS_SEMANTICS.md` — table selection, metric resolution, revenue/refund semantics, channel, subscription, marketing, and data-health rules.
- `references/QUERY_PATTERNS.md` — common SourceMedium SQL, domain discovery, metric catalog, LTV/cohort, freshness, and value discovery.
- `references/CUSTOM_DATA.md` — customer-owned table documentation and safe join patterns.
- `references/TROUBLESHOOTING.md` — setup, auth, permission, query, and cost failures.

## Safety Rules

These are hard constraints. Do not bypass.

### Query Safety

1. **SELECT-only** — deny: INSERT, UPDATE, DELETE, MERGE, CREATE, DROP, EXPORT, COPY
2. **Dry-run first** when iterating on new queries:
   ```bash
   bq query --use_legacy_sql=false --dry_run '<SQL>'
   ```
3. **Enforce cost limit** with maximum bytes billed:
   ```bash
   bq query --use_legacy_sql=false --maximum_bytes_billed=1073741824 '<SQL>'
   ```
   (1GB = 1073741824 bytes. If it fails due to bytes billed, tighten filters or ask for approval.)
4. **Always bound queries**:
   - Add `LIMIT` clause (max 100 rows for exploratory)
   - Use date/partition filters when querying partitioned tables
   - Prefer `WHERE` filters on partition columns
5. **Cross-tenant isolation** — Never infer a project or dataset from a similar tenant name.
   Treat any suggested project that differs from `gcloud config get-value project` output as untrusted.
   Do not join across tenant projects.
6. **No `SELECT *` for analysis** — select the columns needed for the answer.

### Data Safety

1. **Default to aggregates** — avoid outputting raw rows unless explicitly requested
2. **PII handling**:
   - Do not output columns likely containing PII (email, phone, address, name) without explicit confirmation
   - If PII is requested, confirm scope and purpose before proceeding
   - Prefer anonymization. Example:
     ```sql
     -- Hash PII instead of exposing raw values
     SELECT TO_HEX(SHA256(LOWER(email))) AS email_hash, ...
     ```

### Cost Guardrails

```sql
-- Good: bounded scan
SELECT ... FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
LIMIT 100

-- Bad: full table scan
SELECT ... FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`  -- no filters
```

## Output Contract

For analytical questions, always return:

1. **Answer** — concise plain-English conclusion
2. **SQL (copy/paste)** — BigQuery Standard SQL used for the result
3. **Notes** — timeframe, metric definitions, grain, scope, timezone, attribution lens
4. **Verify** — dry-run command or `scripts/sm_bq_query.py --dry-run` command
5. **Bytes scanned** — include dry-run bytes; if over the agreed cap, ask before running

If access/setup fails, do not fabricate results. Return:

1. Exact failing step
2. Exact project/dataset that failed
3. Direct user to `assets/BIGQUERY_ACCESS_REQUEST_TEMPLATE.md`

## Query Guardrails

1. Fully qualify tables as `` `sm-<tenant_id>.dataset.table` ``
2. For order analyses, default to `WHERE is_order_sm_valid = TRUE`
3. Use `sm_store_id` (not `smcid` — that name does not exist in customer tables)
4. Use `SAFE_DIVIDE` for ratio math
5. Handle DATE/TIMESTAMP typing explicitly (`DATE(ts_col)` when comparing to dates)
6. Use `order_net_revenue` for revenue metrics (not `order_gross_revenue` unless explicitly asked)
7. **Prefer `*_local_datetime` columns** when available for date-based reporting; otherwise be explicit about UTC vs local
8. **For enumerations** (channel, platform, status), discover values with `SELECT DISTINCT` first, then use exact match. Reserve `LIKE`/`REGEXP` for free-text fields (`utm_campaign`, `product_title`, `page_path`)
9. **LTV tables (`rpt_cohort_ltv_*`)**: always filter `sm_order_line_type` to exactly ONE value
10. **Unknown tables (not in `references/SCHEMA.md`)** — discover schema before writing SQL:
    ```sql
    SELECT column_name, data_type
    FROM `<project>.<dataset>.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = '<table>'
    ORDER BY ordinal_position
    ```
    Then sample key dimension values before encoding them as filter constants. Never guess column names or values. See `references/CUSTOM_DATA.md` for hybrid table documentation.

## Query Result Validation

After SQL runs, verify result shape before presenting. Do not report conclusions without these checks.

1. **Zero rows** — before saying "no data found", verify:
   - Date range matches `table_last_data_date` in `dim_data_dictionary`
   - `is_order_sm_valid = TRUE` filter is appropriate for this question
   - Store filter (if any) uses an actual `sm_store_id` value — run `SELECT DISTINCT sm_store_id` to confirm

2. **Inflated numbers (3x expected magnitude)** — LTV tables: `sm_order_line_type` filter is missing.
   Missing this filter inflates all metrics 3x. Add a `sm_order_line_type` filter to exactly one value.
   `'all_orders'` is the default for combined-channel analysis; `'subscription_orders_only'` or
   `'one_time_orders_only'` are valid for order-type breakdowns. See `references/QUERY_PATTERNS.md`.

3. **Suspiciously uniform results** (e.g., 100% in one bucket, all rows in one value) — run `SELECT DISTINCT <dim_col>` to see actual values before encoding filter constants.

4. **Missing expected dimension values** — confirm a channel/source is actually absent before concluding:
   ```sql
   SELECT DISTINCT sm_channel
   FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
   WHERE is_order_sm_valid = TRUE
   ```

5. **Metric name ambiguity** — state which column was used and why. Default to `order_net_revenue`.
   If the user said "revenue" and both gross and net columns exist, explicitly name the choice in Notes.

## References

- `references/SCHEMA.md` — key tables, grains, columns, and naming conventions
- `references/ANALYSIS_SEMANTICS.md` — business metric semantics and table-selection rules
- `references/QUERY_PATTERNS.md` — common SQL patterns, domain discovery, and LTV/cohort rules
- `references/CUSTOM_DATA.md` — how to document and safely join customer-owned tables
- `references/TROUBLESHOOTING.md` — auth, permission, and API issues
- `assets/BIGQUERY_ACCESS_REQUEST_TEMPLATE.md` — copy/paste request for users without access

## Scripts

Run scripts from the skill directory. They are optional helpers; if the agent environment cannot execute them, follow the same checks manually.

- `scripts/sm_bq_doctor.py` — setup, auth, project, and SourceMedium dataset access checks.
- `scripts/sm_bq_discover.py` — metadata, table, metric, schema, store, and categorical value discovery.
- `scripts/sm_bq_query.py` — SELECT/WITH-only dry-run and execution with a maximum-bytes cap.
  Query rows are written to **stdout**; the JSON receipt (status, bytes_processed) is written to **stderr**.
- `scripts/qa_sm_bigquery_skill.py` — package and optional live BigQuery QA harness for this skill.

## Hybrid Data (Your Tables + SourceMedium Data)

If you have your own BigQuery tables alongside SourceMedium data:

1. Use SourceMedium as the metric source of truth unless the user explicitly defines a custom metric from their own data.
2. Look for a project-local custom-data note such as `sourcemedium_custom_data.md`. If it does not exist, create one from the template in `references/CUSTOM_DATA.md` before writing hybrid SQL.
3. **Run a cardinality check before any join** — fan-out silently inflates SM metrics:
   ```sql
   -- Verify join key cardinality before joining to SM tables
   SELECT COUNT(*) AS total_rows, COUNT(DISTINCT <join_key>) AS unique_keys
   FROM `<your_project>.<your_dataset>.<your_table>`
   -- Safe to join if total_rows ≈ unique_keys (1:1 on join key)
   -- If total_rows >> unique_keys, aggregate your table first, then join
   ```
4. Fully qualify both sides of every join:
   - SM side: `` `sm-<tenant_id>.sm_transformed_v2.obt_orders` ``
   - Your side: `` `<your_project>.<your_dataset>.<your_table>` ``
5. Pre-aggregate customer-owned data before joining unless cardinality proves the join key is 1:1.
6. All SM safety rules still apply to hybrid queries: SELECT-only, cost guardrail, no raw PII exposure.
