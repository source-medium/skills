# Dashboard SQL

Use this reference when planning dashboard data contracts and writing BI-safe SQL.

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
- Use `rpt_*` tables for pre-aggregated dashboard grains such as executive
  summary, daily ad performance, cohort LTV, messaging, funnel, and returns.
- Use `dim_*`/`fct_*` tables for lower-grain debugging or custom joins.
- Use `sm_experimental` only for MTA and purchase-journey analysis.
- Use customer-owned tables only after documenting grain, join keys, PII, owner,
  date coverage, and cardinality.

## Metric Defaults

| Metric intent | Default |
|---------------|---------|
| Revenue | `order_net_revenue` |
| Gross sales | `order_gross_revenue` |
| Revenue including shipping/taxes | `order_total_revenue` |
| Order count | `COUNT(DISTINCT sm_order_key)` |
| Customer count | `COUNT(DISTINCT sm_customer_key)` |
| AOV | `SAFE_DIVIDE(SUM(order_net_revenue), COUNT(DISTINCT sm_order_key))` |
| Refund rate | `SAFE_DIVIDE(ABS(SUM(order_refunds)), NULLIF(SUM(order_gross_revenue), 0))` |
| Platform ROAS | `SAFE_DIVIDE(SUM(ad_platform_reported_revenue), NULLIF(SUM(ad_spend), 0))` |
| MER / blended ROAS | order revenue / ad spend at a compatible grain |
| CAC / CPA | ad spend / new customers |

Before using a named metric, query
`sm_metadata.dim_semantic_metric_catalog` for preferred name, category, type,
calculation, and dependent metrics.

## BI-Safe Query Rules

- Use BigQuery Standard SQL.
- Fully qualify every table.
- Use `WHERE is_order_sm_valid = TRUE` for order/order-line analyses.
- Prefer `*_local_datetime` date fields for reporting.
- Use `SAFE_DIVIDE` and `NULLIF` for ratios.
- Bound dashboard queries by date and `LIMIT` exploratory query outputs.
- Avoid `SELECT *`; choose fields intentionally.
- Pre-aggregate customer-owned tables before joining unless cardinality proves
  the join key is 1:1.
- Keep dashboard tile queries stable and readable; avoid clever SQL that hides
  metric definitions.

## Validation Queries

Freshness:

```sql
SELECT
  dataset_name,
  table_name,
  MAX(table_last_data_date) AS table_last_data_date,
  LOGICAL_OR(COALESCE(table_has_data, FALSE)) AS table_has_data,
  LOGICAL_OR(COALESCE(table_has_fresh_data_14d, FALSE)) AS table_has_fresh_data_14d
FROM `sm-<tenant_id>.sm_metadata.dim_data_dictionary`
WHERE table_name IN ('obt_orders', 'rpt_executive_summary_daily')
GROUP BY dataset_name, table_name
ORDER BY dataset_name, table_name;
```

Store scope:

```sql
SELECT sm_store_id, COUNT(*) AS row_count
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
GROUP BY sm_store_id
ORDER BY row_count DESC;
```

Categorical values:

```sql
SELECT sm_channel, COUNT(*) AS order_count
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
GROUP BY sm_channel
ORDER BY order_count DESC;
```

Revenue sanity:

```sql
SELECT
  SUM(order_gross_revenue) AS gross_revenue,
  SUM(order_discounts) AS discounts,
  SUM(order_refunds) AS refunds,
  SUM(order_net_revenue) AS net_revenue,
  SUM(order_total_revenue) AS total_revenue
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
```

## Common Dashboard Tiles

Executive overview:

- Scorecards: net revenue, orders, AOV, new customers, ad spend, MER/CAC
- Trend: net revenue and orders over time
- Breakdown: revenue by `sm_channel` / `sm_sub_channel`
- Diagnostics: freshness, attribution coverage, valid order counts

Marketing:

- Scorecards: ad spend, platform ROAS, MER, CAC, new customer revenue
- Trend: spend and platform-reported revenue by platform
- Breakdown: campaign type, channel, platform
- Caveat: for TikTok CPC/CTR/CPM, check and often exclude `ad_campaign_type = 'gmv_max'`

Products:

- Scorecards: product revenue, units sold, gross profit
- Ranking: top products/SKUs by net revenue or units
- Diagnostics: missing SKU rate and product cost coverage

Retention/LTV:

- Use cohort LTV report tables when available.
- Always filter `sm_order_line_type` to exactly one value.
- Avoid showing tiny cohorts as winners without cohort-size context.
