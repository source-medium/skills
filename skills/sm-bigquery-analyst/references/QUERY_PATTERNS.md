# Query Patterns

Common SQL patterns for SourceMedium BigQuery analysis.

## Domain Discovery (Start Here)

Before writing analytical SQL, find out which business areas have data in your warehouse:

```sql
-- What business domains do I have data for?
SELECT
  table_name,
  table_description,
  table_has_data,
  table_has_fresh_data_14d,
  table_last_data_date
FROM `sm-<tenant_id>.sm_metadata.dim_data_dictionary`
WHERE table_has_data = TRUE
  AND dataset_name = 'sm_transformed_v2'
ORDER BY table_name
```

Use the results to decide which questions are answerable:

| Tables present | Domains unlocked |
|----------------|-----------------|
| `obt_orders`, `obt_order_lines` | Revenue, product performance, profitability |
| `obt_customers` | Customer acquisition, retention, subscription status |
| `rpt_ad_performance_daily` | Marketing efficiency, ad spend, ROAS, CPA |
| `rpt_cohort_ltv_*` | LTV curves, retention cohorts |
| `obt_events` | Funnel, session, conversion analysis |
| `obt_purchase_journeys_with_mta_models` | Multi-touch attribution |

## Daily Revenue by Channel

```sql
SELECT
  DATE(order_processed_at_local_datetime) AS order_date,
  sm_channel,
  COUNT(sm_order_key) AS order_count,
  SUM(order_net_revenue) AS revenue
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY order_date, sm_channel
ORDER BY order_date DESC
LIMIT 100
```

## New Customer Acquisition by Source

```sql
SELECT
  DATE(order_processed_at_local_datetime) AS order_date,
  sm_utm_source_medium,
  COUNT(DISTINCT sm_customer_key) AS new_customers,
  SUM(order_net_revenue) AS revenue,
  SAFE_DIVIDE(SUM(order_net_revenue), COUNT(DISTINCT sm_customer_key)) AS avg_first_order_value
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND order_sequence = '1st_order'
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY order_date, sm_utm_source_medium
ORDER BY order_date DESC
LIMIT 100
```

## Product Performance with Margins

```sql
SELECT
  product_title,
  sku,
  SUM(order_line_quantity) AS units_sold,
  SUM(order_line_net_revenue) AS revenue,
  SUM(order_line_product_cost) AS cogs,
  SUM(order_line_gross_profit) AS profit,
  SAFE_DIVIDE(SUM(order_line_gross_profit), SUM(order_line_net_revenue)) AS profit_margin
FROM `sm-<tenant_id>.sm_transformed_v2.obt_order_lines`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY product_title, sku
ORDER BY revenue DESC
LIMIT 20
```

## Ad Performance Summary

```sql
SELECT
  source_system,
  sm_channel,
  SUM(ad_spend) AS spend,
  SUM(ad_impressions) AS impressions,
  SUM(ad_clicks) AS clicks,
  SAFE_DIVIDE(SUM(ad_clicks), SUM(ad_impressions)) AS ctr,
  SAFE_DIVIDE(SUM(ad_spend), SUM(ad_clicks)) AS cpc
FROM `sm-<tenant_id>.sm_transformed_v2.rpt_ad_performance_daily`
WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY source_system, sm_channel
ORDER BY spend DESC
LIMIT 50
```

## Platform ROAS by Campaign Type

Use this for platform-reported ad efficiency. For blended MER/ROAS, resolve the
metric in `dim_semantic_metric_catalog` and use order revenue plus ad spend at a
compatible grain.

```sql
SELECT
  sm_store_id,
  source_system,
  COALESCE(NULLIF(ad_campaign_type, ''), '(unknown)') AS campaign_type,
  SUM(ad_platform_reported_revenue) AS platform_reported_revenue,
  SUM(ad_spend) AS ad_spend,
  SAFE_DIVIDE(SUM(ad_platform_reported_revenue), NULLIF(SUM(ad_spend), 0)) AS platform_roas
FROM `sm-<tenant_id>.sm_transformed_v2.rpt_ad_performance_daily`
WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND ad_spend > 0
GROUP BY sm_store_id, source_system, campaign_type
ORDER BY platform_roas DESC
LIMIT 50
```

For TikTok CPC, CTR, and CPM analysis, check `ad_campaign_type` first. Exclude
`ad_campaign_type = 'gmv_max'` when the user wants ordinary TikTok Ads ratios,
because GMV Max rows can have spend without ordinary click/impression coverage.

## LTV Cohort Analysis (CRITICAL)

Queries against `rpt_cohort_ltv_*` tables have strict requirements:

### Rules

1. **Filter `sm_order_line_type` to exactly ONE value** — the table has 3 rows per cohort. Without this filter, all metrics inflate 3x.
   - Valid values: `'all_orders'`, `'subscription_orders_only'`, `'one_time_orders_only'`
   - Valid: `WHERE sm_order_line_type = 'all_orders'`
   - Valid: `GROUP BY sm_order_line_type` (when comparing order types)
   - Invalid: no filter at all, or `IN ('all_orders', 'subscription_orders_only')`

2. **`months_since_first_order` is 0-indexed** — 0 = cohort month, 12 = 12-month mark.

3. **Aggregation** — use `AVG(SAFE_DIVIDE(metric, cohort_size))`, not `SAFE_DIVIDE(SUM(metric), SUM(cohort_size))`.

4. **Dimension** — use `acquisition_order_filter_dimension = 'source/medium'` for marketing analysis.

5. **Revenue column** — use `cumulative_order_net_revenue` (not `cumulative_gross_profit`).

### Example Query

```sql
SELECT
  cohort_month,
  months_since_first_order,
  AVG(SAFE_DIVIDE(cumulative_order_net_revenue, cohort_size)) AS avg_ltv
FROM `sm-<tenant_id>.sm_transformed_v2.rpt_cohort_ltv_by_first_valid_purchase_attribute_no_product_filters`
WHERE sm_order_line_type = 'all_orders'
  AND acquisition_order_filter_dimension = 'source/medium'
  AND cohort_month >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 24 MONTH)
  AND months_since_first_order <= 12
GROUP BY cohort_month, months_since_first_order
ORDER BY cohort_month, months_since_first_order
LIMIT 500
```

## Discover Categorical Values (Before Filtering)

Always discover values before using `LIKE` or `IN` on categorical columns:

```sql
-- See what channel values exist
SELECT sm_channel, COUNT(*) AS n
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
GROUP BY sm_channel ORDER BY n DESC

-- See what order sequence values exist
SELECT subscription_order_sequence, COUNT(*) AS n
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
GROUP BY subscription_order_sequence ORDER BY n DESC
```

## Check Data Freshness

Use `sm_metadata.dim_data_dictionary` for freshness and schema discovery:

```sql
-- Check which tables have fresh data
SELECT 
  table_name, 
  table_has_data, 
  table_has_fresh_data_14d, 
  table_last_data_date
FROM `sm-<tenant_id>.sm_metadata.dim_data_dictionary`
WHERE table_has_data = TRUE
ORDER BY table_name

-- Check specific table freshness
SELECT table_name, table_last_data_date
FROM `sm-<tenant_id>.sm_metadata.dim_data_dictionary`
WHERE table_name IN ('obt_orders', 'obt_customers', 'obt_order_lines')
```

## Revenue Sanity Check

Discounts and refunds are usually negative or zero. Use this when reconciling
gross, net, and total revenue.

```sql
SELECT
  sm_store_id,
  SUM(order_gross_revenue) AS gross_revenue,
  SUM(order_discounts) AS discounts,
  SUM(order_refunds) AS refunds,
  SUM(order_net_revenue) AS net_revenue,
  SUM(order_net_revenue_before_refunds) AS net_revenue_before_refunds,
  SUM(order_total_revenue) AS total_revenue
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY sm_store_id
ORDER BY net_revenue DESC
LIMIT 50
```

## Channel Mapping Debug

Use this when channel results look wrong or too much revenue lands in one bucket.

```sql
SELECT
  sm_order_key,
  sm_channel,
  sm_sub_channel,
  sm_default_channel,
  sm_order_sales_channel,
  source_system_sales_channel,
  sm_utm_source_medium,
  order_discount_codes_csv
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY order_processed_at_local_datetime DESC
LIMIT 200
```

## Discover Column Stats and Values

Use `sm_metadata.dim_data_dictionary` to discover column-level metadata:

```sql
-- See column null rates and distinct counts
SELECT 
  column_name, 
  column_null_percentage,
  column_distinct_count
FROM `sm-<tenant_id>.sm_metadata.dim_data_dictionary`
WHERE table_name = 'obt_orders'
ORDER BY column_null_percentage DESC

-- Discover categorical value distribution for a column
SELECT 
  column_name,
  categorical_value_distribution
FROM `sm-<tenant_id>.sm_metadata.dim_data_dictionary`
WHERE table_name = 'obt_orders'
  AND column_name = 'sm_channel'
```

## Discover Available Metrics

Use `sm_metadata.dim_semantic_metric_catalog` to discover 180+ pre-defined metrics:

```sql
-- Find all revenue metrics
SELECT metric_name, metric_label, metric_type, calculation
FROM `sm-<tenant_id>.sm_metadata.dim_semantic_metric_catalog`
WHERE metric_category = 'revenue'
ORDER BY metric_name

-- Find marketing efficiency metrics (MER, ROAS, CAC, etc.)
SELECT metric_name, metric_description, calculation, dependent_metrics
FROM `sm-<tenant_id>.sm_metadata.dim_semantic_metric_catalog`
WHERE metric_category = 'marketing'
ORDER BY metric_name

-- Resolve abbreviated metric names
SELECT metric_name, preferred_metric_name, metric_description
FROM `sm-<tenant_id>.sm_metadata.dim_semantic_metric_catalog`
WHERE metric_name IN ('aov', 'mer', 'cac', 'roas')

-- Find metrics by data source
SELECT metric_name, metric_type, metric_category
FROM `sm-<tenant_id>.sm_metadata.dim_semantic_metric_catalog`
WHERE semantic_model_name = 'orders'
ORDER BY metric_category, metric_name
```

Common metric aliases:
- `aov` → `average_order_value_net`
- `mer` → `marketing_efficiency_ratio`
- `cac` → `customer_acquisition_cost`
- `roas` → `return_on_ad_spend`

## MTA / Attribution Queries

If the question involves multi-touch attribution, use the experimental dataset:

```sql
FROM `sm-<tenant_id>.sm_experimental.obt_purchase_journeys_with_mta_models`
```

For standard order/revenue analysis, use `sm_transformed_v2` tables.
