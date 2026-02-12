# Query Patterns

Common SQL patterns for SourceMedium BigQuery analysis.

## Daily Revenue by Channel

```sql
SELECT
  DATE(order_processed_at_local_datetime) AS order_date,
  sm_channel,
  COUNT(sm_order_key) AS order_count,
  SUM(order_net_revenue) AS revenue
FROM `your_project.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1, 2
ORDER BY 1 DESC
```

## New Customer Acquisition by Source

```sql
SELECT
  DATE(order_processed_at_local_datetime) AS order_date,
  sm_utm_source_medium,
  COUNT(DISTINCT sm_customer_key) AS new_customers,
  SUM(order_net_revenue) AS revenue,
  SAFE_DIVIDE(SUM(order_net_revenue), COUNT(DISTINCT sm_customer_key)) AS avg_first_order_value
FROM `your_project.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND order_sequence = '1st_order'
GROUP BY 1, 2
ORDER BY 1 DESC
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
FROM `your_project.sm_transformed_v2.obt_order_lines`
WHERE is_order_sm_valid = TRUE
GROUP BY 1, 2
ORDER BY revenue DESC
LIMIT 20
```

## Ad Performance Summary

```sql
SELECT
  ad_platform,
  SUM(ad_spend) AS spend,
  SUM(ad_impressions) AS impressions,
  SUM(ad_clicks) AS clicks,
  SAFE_DIVIDE(SUM(ad_clicks), SUM(ad_impressions)) AS ctr,
  SAFE_DIVIDE(SUM(ad_spend), SUM(ad_clicks)) AS cpc
FROM `your_project.sm_transformed_v2.rpt_ad_performance_daily`
WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1
ORDER BY spend DESC
```

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
FROM `your_project.sm_transformed_v2.rpt_cohort_ltv_by_first_valid_purchase_attribute_no_product_filters`
WHERE sm_order_line_type = 'all_orders'
  AND acquisition_order_filter_dimension = 'source/medium'
  AND months_since_first_order <= 12
GROUP BY 1, 2
ORDER BY 1, 2
```

## Discover Categorical Values (Before Filtering)

Always discover values before using `LIKE` or `IN` on categorical columns:

```sql
-- See what channel values exist
SELECT sm_channel, COUNT(*) AS n
FROM `your_project.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
GROUP BY 1 ORDER BY 2 DESC

-- See what order sequence values exist
SELECT subscription_order_sequence, COUNT(*) AS n
FROM `your_project.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
GROUP BY 1 ORDER BY 2 DESC
```

## Check Data Freshness

Use `sm_metadata.dim_data_dictionary` for comprehensive data freshness and schema discovery:

```sql
-- Check which tables have fresh data
SELECT 
  table_name, 
  table_has_data, 
  table_has_fresh_data_14d, 
  table_last_data_date
FROM `your_project.sm_metadata.dim_data_dictionary`
WHERE table_has_data = TRUE
ORDER BY table_name

-- Check specific table freshness
SELECT table_name, table_last_data_date
FROM `your_project.sm_metadata.dim_data_dictionary`
WHERE table_name IN ('obt_orders', 'obt_customers', 'obt_order_lines')
```

You can also use the `__TABLES__` metadata table:

```sql
SELECT
  table_id,
  TIMESTAMP_MILLIS(last_modified_time) AS last_modified
FROM `your_project.sm_transformed_v2.__TABLES__`
WHERE table_id IN ('obt_orders', 'obt_customers', 'obt_order_lines')
ORDER BY last_modified DESC
```

## Discover Column Stats and Values

Use `sm_metadata.dim_data_dictionary` to discover column-level metadata:

```sql
-- See column null rates and distinct counts
SELECT 
  column_name, 
  column_null_percentage,
  column_distinct_count
FROM `your_project.sm_metadata.dim_data_dictionary`
WHERE table_name = 'obt_orders'
ORDER BY column_null_percentage DESC

-- Discover categorical value distribution for a column
SELECT 
  column_name,
  categorical_value_distribution
FROM `your_project.sm_metadata.dim_data_dictionary`
WHERE table_name = 'obt_orders'
  AND column_name = 'sm_channel'
```

## Discover Available Metrics

Use `sm_metadata.dim_semantic_metric_catalog` to discover 180+ pre-defined metrics:

```sql
-- Find all revenue metrics
SELECT metric_name, metric_label, metric_type, calculation
FROM `your_project.sm_metadata.dim_semantic_metric_catalog`
WHERE metric_category = 'revenue'
ORDER BY metric_name

-- Find marketing efficiency metrics (MER, ROAS, CAC, etc.)
SELECT metric_name, metric_description, calculation, dependent_metrics
FROM `your_project.sm_metadata.dim_semantic_metric_catalog`
WHERE metric_category = 'marketing'
ORDER BY metric_name

-- Resolve abbreviated metric names
SELECT metric_name, preferred_metric_name, metric_description
FROM `your_project.sm_metadata.dim_semantic_metric_catalog`
WHERE metric_name IN ('aov', 'mer', 'cac', 'roas')

-- Find metrics by data source
SELECT metric_name, metric_type, metric_category
FROM `your_project.sm_metadata.dim_semantic_metric_catalog`
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
FROM `your_project.sm_experimental.obt_purchase_journeys_with_mta_models`
```

For standard order/revenue analysis, use `sm_transformed_v2` tables.
