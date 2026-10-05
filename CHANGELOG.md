# Changelog

## Unreleased

### Accuracy pass against the current platform

- `sm-bigquery-analyst` 2.0:
  - States what each plan can do. The SourceMedium MCP works on every plan and
    is used first. Direct warehouse access (`bq` with the user's own Google
    account) is part of Pro: the scripts, in-warehouse joins to the customer's
    own tables, `sm_sources`, and results beyond the MCP's limits.
  - Examples use lane-neutral names (`<project>.<sm_transformed_v2>`), so the
    same SQL runs through the MCP on the shared warehouse (`sourcemedium-bi`,
    `<tenant>_sm_*`) and on a dedicated one. The doctor resolves and prints the
    real names for direct access.
  - Notes that `query_metrics` refuses the new- and repeat-customer metrics
    today, and shows the SQL that computes them.
  - Fixes cohort LTV: sum, then divide, across channels and segments. It was
    `AVG(cumulative / cohort_size)`, which understated real cohorts by 11% to 15%.
  - New customers use `sm_valid_order_sequence`, not `order_sequence`.
  - Metric catalog guidance: `calculation` is not SQL, so apply
    `filter_condition` and aggregate before dividing. Discovery now returns the
    filter columns.
  - Corrects grains (`rpt_ad_performance_daily` is ad-level and not unique;
    `rpt_executive_summary_daily` is per store, channel, sub-channel and date),
    channel values and assignment, `order_total_revenue` (duties excluded), and
    string normalization scope.
  - Removes `obt_events`, which never existed. Fixes the `order_date` column in
    the custom-data join example. Order join keys now include `source_system`.
  - Documents the tables available only on the dedicated warehouse, plus
    `sm_views`, `sm_utils`, `sm_sources` and the newer metadata tables.
  - The access guide reflects how access works: SourceMedium workspace
    membership, not an IAM request to the customer's own admin.
  - `sm_bq_query.py` no longer truncates results at 100 rows silently. It
    returns up to `--max-rows` and exits 7 with status `truncated` when there
    are more. SELECT-only is enforced from BigQuery's own statement type, and
    keywords inside string literals no longer cause false rejections. The
    receipt lists referenced tables, and byte estimates parse "upper bound"
    dry-runs.
  - `sm_bq_discover.py` caps every query's bytes and reports truncation.
  - Documents what `is_order_sm_valid` really excludes: fully refunded orders,
    and every channel other than online_dtc, amazon, tiktok_shop, retail and
    wholesale. Also documents that guest checkouts are almost all
    `repeat_order`, that some catalog `filter_condition` columns are internal
    names (`valid_order_sequence`), and that two report tables publish
    `sm_channel` unnormalized.
  - `sm_bq_query.py` no longer rejects valid SQL whose comments contain a quote.
- `sm-dashboard-builder` 1.1: works on every plan through the MCP; BI-tool
  handoffs are marked as needing direct warehouse access. `--strict` now refuses unresolved placeholders,
  non-date freshness checks, and tiles marked `fail`. LTV, new-customer and
  cross-table ratio defaults are corrected, and templates use lane-neutral names.
- `sm-pipeline-builder` 1.1: states that it needs direct warehouse access
  (Pro). The validator rejects shared-warehouse
  SourceMedium datasets (`<tenant>_sm_*`), `smdelivery_*`, and the
  `sourcemedium-bi` project as destinations. Integration guidance covers where
  customer tables may live, order joins on `sm_store_id` + `source_system` +
  `order_id`, and gating on SourceMedium's publish log.
- QA:
  - `scripts/qa_sql_examples.py` dry-runs and executes every shipped SQL
    example against a live warehouse and fails on unknown placeholders.
  - `just qa-live` runs it on both warehouse layouts.

### Earlier

- Expanded `sm-bigquery-analyst` with stronger SourceMedium metadata discovery,
  custom dataset support, semantic metric guidance, QA tooling, eval metadata,
  and OpenAI/Codex skill metadata.
- Added `sm-dashboard-builder` for correctness-first BI dashboard creation from
  SourceMedium BigQuery data and operator-owned warehouse tables.
- Added dashboard manifest validation, strict publish checks, HTML rendering,
  metric contract templates, Metabase handoff templates, and example dashboard
  manifests.
- Added package-level install, update, and QA guidance.
- Added `sm-pipeline-builder` for spec-first bespoke data pipelines that land
  in customer-owned BigQuery datasets alongside SourceMedium data, or publish
  customer-owned tables out of BigQuery into a system the operator owns.
  Ships incremental-load, BigQuery, data-quality, operations, and integration
  references plus a readiness checklist. The spec validator enforces the hard
  rules a spec can break on paper: writes into `sm_*` datasets, credential
  values carried instead of secret names, primary keys not derivable from the
  declared grain, and `append_restate` streams with no window column to make
  the fetch and delete windows identical. Malformed specs exit 2 with a
  message rather than a traceback.
