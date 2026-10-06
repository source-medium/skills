# Dashboard SQL

Use this reference when planning dashboard data contracts and writing BI-safe SQL.

## Names and Route

- SourceMedium warehouses come in two layouts: a dedicated project with
  `sm_transformed_v2`, `sm_metadata`, ... or the shared `sourcemedium-bi` project
  with `<tenant>_sm_transformed_v2`, `<tenant>_sm_metadata`, .... Examples here
  write `` `<project>.<sm_transformed_v2>.obt_orders` ``; substitute the names
  reported by the SourceMedium MCP's `get_data_context` (or, with direct
  warehouse access and the `sm-bigquery-analyst` skill installed, its
  `scripts/sm_bq_doctor.py`). A
  publish-ready manifest has no `<...>` placeholders left, and strict validation
  enforces that.
- On every plan, use the SourceMedium MCP: `query_metrics` for catalog-metric
  tiles (it compiles SourceMedium's definition and returns the compiled SQL,
  which becomes the tile's SQL receipt) and `run_bigquery_sql` for custom tiles.
  `query_metrics` refuses cross-table ratios (`underlying_model`
  `Multiple models`, such as CAC and MER); write those tiles' SQL from the
  catalog row and note why. With direct warehouse access (Pro), `bq` works too.

## SQL Contract Per Tile

Every dashboard tile needs:

- `tile_id`
- Business question
- Metric definition and formula
- Table(s) and grain
- Timeframe and date field
- Store/channel/customer scope
- Filters and exclusions
- SQL
- Dry-run bytes
- Freshness check
- Result shape: row count, columns, nulls, and important categorical values
- Caveats

Use `assets/metric_contract_template.json` for metric definitions and keep
`metric_contract_ids` on each chart/table tile so the rendered dashboard can be
audited back to the BI contract.

## SourceMedium Table Selection

- Start with `obt_*` tables for business-ready analysis.
- Use `rpt_*` tables for pre-aggregated grains: daily executive summary (one row
  per store, channel, sub-channel, and date), daily ad performance (ad-level and
  not unique: always aggregate), cohort LTV, messaging, funnel.
- `dim_*`/`fct_*` tables are mostly dedicated-warehouse only; on the shared
  warehouse, use the `obt_*` table covering the same ground.
- Use `<sm_experimental>` only for MTA and purchase-journey analysis.
- Use customer-owned tables only after documenting grain, join keys, PII, owner,
  date coverage, and cardinality.

## Metric Defaults

Resolve every named metric in `<sm_metadata>.dim_semantic_metric_catalog` first:
`preferred_metric_name`, `calculation`, `filter_condition`, `underlying_model`,
`dependent_metrics`. `calculation` is documentation, not runnable SQL; the
filter is in `filter_condition`, written in the customer tables' column
names. The catalog's definitions today:

| Metric intent | Definition |
|---------------|------------|
| Revenue | `SUM(order_net_revenue)`, valid orders |
| Gross sales | `SUM(order_gross_revenue)`, valid orders |
| Revenue with shipping and taxes | `SUM(order_total_revenue)` (duties excluded) |
| Orders | `COUNT(sm_order_key)`, valid orders |
| AOV | `SAFE_DIVIDE(SUM(order_net_revenue), COUNT(sm_order_key))`, valid orders |
| New customers | `COUNT(DISTINCT sm_customer_key)`, valid, `sm_valid_order_sequence = '1st_order'`, `sm_channel IN ('online_dtc', 'amazon', 'tiktok_shop')` |
| Refund rate | Catalog `refund_rate` is `SUM(order_refunds) / SUM(order_gross_revenue)` on valid orders, a negative number because refunds are stored negative; display it with `ABS()` and say so. Valid orders exclude fully refunded ones, so this is partial refunds only |
| Ad spend | `SUM(ad_spend)` on `rpt_ad_performance_daily` |
| Platform ROAS | `SAFE_DIVIDE(SUM(ad_platform_reported_revenue), SUM(ad_spend))` |
| MER / blended ROAS | order net revenue / ad spend, each aggregated on its own table, joined on date |
| CAC | ad spend / first valid orders in those three channels, same pattern (the catalog's `cpa` row divides by new customers instead) |

## BI-Safe Query Rules

- Use BigQuery Standard SQL and fully qualify every table.
- `WHERE is_order_sm_valid = TRUE` for order and order-line tiles.
- Prefer `*_local_datetime` date fields for reporting.
- Ratios: aggregate first, then divide, with `SAFE_DIVIDE`. Never average a
  per-row ratio, and never sum a ratio across chart rows: recompute it at the
  displayed grain.
- Bound dashboard queries by date; `LIMIT` exploratory outputs.
- Avoid `SELECT *`; choose fields intentionally.
- Pre-aggregate customer-owned tables before joining unless cardinality proves
  the join key is 1:1.
- Keep tile queries stable and readable; avoid clever SQL that hides metric
  definitions.

## Validation Queries

Freshness:

```sql
SELECT
  table_name,
  MAX(table_last_data_date) AS table_last_data_date,
  LOGICAL_OR(table_has_data) AS table_has_data,
  LOGICAL_OR(table_has_fresh_data_14d) AS table_has_fresh_data_14d
FROM `<project>.<sm_metadata>.dim_data_dictionary`
WHERE ENDS_WITH(dataset_name, 'sm_transformed_v2')
  AND table_name IN ('obt_orders', 'rpt_ad_performance_daily', 'rpt_executive_summary_daily')
GROUP BY table_name
ORDER BY table_name
```

Store scope:

```sql
SELECT sm_store_id, COUNT(*) AS orders
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY sm_store_id
ORDER BY orders DESC
```

Categorical values:

```sql
SELECT sm_channel, COUNT(*) AS orders
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY sm_channel
ORDER BY orders DESC
```

Revenue sanity (net = gross + discounts + refunds, all stored with their sign):

```sql
SELECT
  SUM(order_gross_revenue) AS gross_revenue,
  SUM(order_discounts) AS discounts,
  SUM(order_refunds) AS refunds,
  SUM(order_net_revenue) AS net_revenue,
  SUM(order_total_revenue) AS total_revenue
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
```

## Common Dashboard Tiles

Executive overview:

- Scorecards: net revenue, orders, AOV, new customers, ad spend, MER/CAC
- Trend: net revenue and orders over time
- Breakdown: revenue by `sm_channel` / `sm_sub_channel`
- Diagnostics: freshness, attribution coverage, valid order counts
- `rpt_executive_summary_daily` is a convenient daily rollup, but its revenue
  need not reconcile exactly to `obt_orders`. When a scorecard must match
  SourceMedium's catalog number, compute it from `obt_orders`.

Marketing:

- Scorecards: ad spend, platform ROAS, MER, CAC, new customer revenue
- Trend: spend and platform-reported revenue by platform
- Breakdown: campaign type, channel, platform
- Caveat: TikTok GMV Max rows (`ad_campaign_type = 'gmv_max'`) carry spend with
  NULL clicks and impressions; exclude them from CPC, CTR, and CPM tiles and say so

Products:

- Scorecards: product revenue, units sold, gross profit
- Ranking: top products/SKUs by net revenue or units
- Diagnostics: missing SKU rate and product cost coverage

Retention/LTV (cohort table
`rpt_cohort_ltv_by_first_valid_purchase_attribute_no_product_filters`):

- Pin one `sm_order_line_type` and one `acquisition_order_filter_dimension`
  (`no_filters` for the whole cohort); the table publishes `online_dtc` and
  `amazon` as separate rows, so filter `sm_channel` or sum across it.
- LTV is `SAFE_DIVIDE(SUM(cumulative_order_net_revenue), SUM(cohort_size))` at the
  displayed grain, never an average of per-row ratios.
- Show only mature offsets: for N months, `cohort_month` at least N + 1 months
  before the current month.
- Show cohort size next to every LTV, and flag cohorts under a stated minimum
  (10 customers is SourceMedium's own floor) instead of ranking them.
