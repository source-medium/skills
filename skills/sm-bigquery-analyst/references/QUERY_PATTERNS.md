# Query Patterns

Copy/paste SQL for SourceMedium BigQuery. Replace `<project>` and the `<sm_*>`
dataset names with the ones `get_data_context` reports (see `SCHEMA.md`). Run
them through the MCP's `run_bigquery_sql` on every plan, or with `bq` given
direct warehouse access. Definitions behind each query are in
`ANALYSIS_SEMANTICS.md`. Every query here is dry-run and executed against a live
warehouse by the package QA.

## Start Here: What Data Exists

```sql
-- One row per table, with freshness. The dictionary holds one row per column,
-- so fold it to tables.
SELECT
  table_name,
  ANY_VALUE(table_description) AS table_description,
  LOGICAL_OR(table_has_data) AS table_has_data,
  LOGICAL_OR(table_has_fresh_data_14d) AS table_has_fresh_data_14d,
  MAX(table_last_data_date) AS table_last_data_date
FROM `<project>.<sm_metadata>.dim_data_dictionary`
WHERE ENDS_WITH(dataset_name, 'sm_transformed_v2')
GROUP BY table_name
HAVING table_has_data
ORDER BY table_name
```

| Tables present | Questions they answer |
|----------------|-----------------------|
| `obt_orders`, `obt_order_lines` | Revenue, orders, AOV, products, margins, new vs repeat |
| `obt_customers` | Acquisition, retention, subscription status |
| `rpt_ad_performance_daily` | Spend, platform ROAS, CPC, CTR; with orders, MER and CAC |
| `rpt_cohort_ltv_by_first_valid_purchase_attribute_no_product_filters` | Cohort LTV and retention |
| `obt_funnel_event_history` | Funnel, sessions, conversion |
| `<sm_experimental>.obt_purchase_journeys_with_mta_models` | Multi-touch attribution |

## Freshness of Specific Tables

```sql
SELECT
  table_name,
  MAX(table_last_data_date) AS table_last_data_date,
  LOGICAL_OR(table_has_fresh_data_14d) AS table_has_fresh_data_14d
FROM `<project>.<sm_metadata>.dim_data_dictionary`
WHERE ENDS_WITH(dataset_name, 'sm_transformed_v2')
  AND table_name IN ('obt_orders', 'obt_customers', 'obt_order_lines', 'rpt_ad_performance_daily')
GROUP BY table_name
ORDER BY table_name
```

## Column Stats and Values From the Dictionary

```sql
-- Null rates and distinct counts, per store
SELECT sm_store_id, column_name, column_null_percentage, column_distinct_count
FROM `<project>.<sm_metadata>.dim_data_dictionary`
WHERE ENDS_WITH(dataset_name, 'sm_transformed_v2')
  AND table_name = 'obt_orders'
ORDER BY column_null_percentage DESC
LIMIT 50

-- Categorical value distribution for one column
SELECT sm_store_id, categorical_value_distribution
FROM `<project>.<sm_metadata>.dim_data_dictionary`
WHERE ENDS_WITH(dataset_name, 'sm_transformed_v2')
  AND table_name = 'obt_orders'
  AND column_name = 'sm_channel'
```

## Discover Categorical Values Directly

```sql
SELECT sm_channel, COUNT(*) AS orders
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY sm_channel
ORDER BY orders DESC
```

## Metric Catalog

```sql
-- Resolve aliases and read a metric's real definition, filter included
SELECT
  metric_name,
  preferred_metric_name,
  metric_type,
  underlying_model,
  calculation,
  has_filter,
  filter_condition,
  metric_time_expression,
  dependent_metrics
FROM `<project>.<sm_metadata>.dim_semantic_metric_catalog`
WHERE metric_name IN ('aov', 'mer', 'cac', 'roas', 'new_customers', 'order_net_revenue')

-- All metrics on one table
SELECT metric_name, metric_type, metric_category, has_filter, filter_condition
FROM `<project>.<sm_metadata>.dim_semantic_metric_catalog`
WHERE semantic_model_name = 'obt_orders'
ORDER BY metric_category, metric_name

-- Search by topic
SELECT metric_name, metric_label, metric_description, calculation, filter_condition
FROM `<project>.<sm_metadata>.dim_semantic_metric_catalog`
WHERE metric_category = 'marketing'
ORDER BY metric_name
```

## Store Scope

```sql
SELECT sm_store_id, COUNT(*) AS orders, SUM(order_net_revenue) AS net_revenue
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY sm_store_id
ORDER BY net_revenue DESC
```

Add `AND sm_store_id = '<store id>'` to any query below for a single store.

## Daily Revenue, Orders, and AOV by Channel

```sql
SELECT
  DATE(order_processed_at_local_datetime) AS order_date,
  sm_channel,
  COUNT(sm_order_key) AS orders,
  SUM(order_net_revenue) AS net_revenue,
  SAFE_DIVIDE(SUM(order_net_revenue), COUNT(sm_order_key)) AS aov_net
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY order_date, sm_channel
ORDER BY order_date DESC, net_revenue DESC
LIMIT 500
```

## New Customers by Source

```sql
SELECT
  sm_utm_source_medium,
  COUNT(DISTINCT sm_customer_key) AS new_customers,
  SUM(order_net_revenue) AS first_order_net_revenue,
  SAFE_DIVIDE(SUM(order_net_revenue), COUNT(sm_order_key)) AS first_order_aov
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND sm_valid_order_sequence = '1st_order'
  AND sm_channel IN ('online_dtc', 'amazon', 'tiktok_shop')
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY sm_utm_source_medium
ORDER BY new_customers DESC
LIMIT 50
```

## MER, CAC, and Blended ROAS

Cross-table ratios: aggregate each side on its own table, join on date, divide.

```sql
WITH orders AS (
  SELECT
    DATE(order_processed_at_local_datetime) AS report_date,
    SUM(order_net_revenue) AS net_revenue,
    COUNTIF(sm_valid_order_sequence = '1st_order'
            AND sm_channel IN ('online_dtc', 'amazon', 'tiktok_shop')) AS new_customer_orders
  FROM `<project>.<sm_transformed_v2>.obt_orders`
  WHERE is_order_sm_valid = TRUE
    AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY report_date
),
spend AS (
  SELECT date AS report_date, SUM(ad_spend) AS ad_spend
  FROM `<project>.<sm_transformed_v2>.rpt_ad_performance_daily`
  WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY report_date
)
SELECT
  SUM(o.net_revenue) AS net_revenue,
  SUM(s.ad_spend) AS ad_spend,
  SUM(o.new_customer_orders) AS new_customer_orders,
  SAFE_DIVIDE(SUM(o.net_revenue), SUM(s.ad_spend)) AS mer,
  SAFE_DIVIDE(SUM(s.ad_spend), SUM(o.new_customer_orders)) AS cac
FROM orders AS o
FULL OUTER JOIN spend AS s USING (report_date)
```

## Product Performance With Margins

```sql
SELECT
  product_title,
  sku,
  SUM(order_line_quantity) AS units_sold,
  SUM(order_line_net_revenue) AS net_revenue,
  SUM(order_line_product_cost) AS product_cost,
  SUM(order_line_gross_profit) AS gross_profit,
  SAFE_DIVIDE(SUM(order_line_gross_profit), SUM(order_line_net_revenue)) AS gross_margin
FROM `<project>.<sm_transformed_v2>.obt_order_lines`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY product_title, sku
ORDER BY net_revenue DESC
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
FROM `<project>.<sm_transformed_v2>.rpt_ad_performance_daily`
WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND COALESCE(ad_campaign_type, '') != 'gmv_max'
GROUP BY source_system, sm_channel
ORDER BY spend DESC
LIMIT 50
```

TikTok GMV Max rows carry spend with NULL clicks and impressions, so they are
excluded from click and impression ratios here. Report their spend separately.

## Platform ROAS by Campaign Type

Platform-reported revenue is the ad platform's claim, not order revenue.

```sql
SELECT
  source_system,
  COALESCE(NULLIF(ad_campaign_type, ''), '(unknown)') AS campaign_type,
  SUM(ad_spend) AS ad_spend,
  SUM(ad_platform_reported_revenue) AS platform_reported_revenue,
  SAFE_DIVIDE(SUM(ad_platform_reported_revenue), SUM(ad_spend)) AS platform_roas
FROM `<project>.<sm_transformed_v2>.rpt_ad_performance_daily`
WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY source_system, campaign_type
HAVING ad_spend > 0
ORDER BY ad_spend DESC
LIMIT 50
```

## Cohort LTV

Rules are in `ANALYSIS_SEMANTICS.md` under Cohort LTV: pin one line type and one
dimension, sum across channels and stores, then divide.

```sql
-- 6-month net revenue LTV per acquisition month, whole cohort, all channels
SELECT
  cohort_month,
  SUM(cohort_size) AS customers,
  SAFE_DIVIDE(SUM(cumulative_order_net_revenue), SUM(cohort_size)) AS ltv_net_6m
FROM `<project>.<sm_transformed_v2>.rpt_cohort_ltv_by_first_valid_purchase_attribute_no_product_filters`
WHERE sm_order_line_type = 'all_orders'
  AND acquisition_order_filter_dimension = 'no_filters'
  AND months_since_first_order = 6
  AND cohort_month >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 24 MONTH)
  AND cohort_month <= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 7 MONTH)
GROUP BY cohort_month
ORDER BY cohort_month
```

```sql
-- LTV curve by acquisition source/medium, mature cohorts only
SELECT
  acquisition_order_filter_dimension_value AS source_medium,
  months_since_first_order,
  SUM(cohort_size) AS customers,
  SAFE_DIVIDE(SUM(cumulative_order_net_revenue), SUM(cohort_size)) AS ltv_net
FROM `<project>.<sm_transformed_v2>.rpt_cohort_ltv_by_first_valid_purchase_attribute_no_product_filters`
WHERE sm_order_line_type = 'all_orders'
  AND acquisition_order_filter_dimension = 'source/medium'
  AND months_since_first_order <= 6
  AND cohort_month >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 18 MONTH)
  AND cohort_month <= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 7 MONTH)
GROUP BY source_medium, months_since_first_order
HAVING SUM(cohort_size) >= 10
ORDER BY customers DESC, months_since_first_order
LIMIT 500
```

The `HAVING` drops segment-offsets below 10 customers; report how many were
dropped if the user is ranking segments.

## Subscription vs One-Time Orders

```sql
SELECT
  sm_order_type,
  subscription_order_sequence,
  COUNT(sm_order_key) AS orders,
  SUM(order_net_revenue) AS net_revenue
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY sm_order_type, subscription_order_sequence
ORDER BY net_revenue DESC
```

## Revenue Reconciliation

Discounts and refunds are negative, so net = gross + discounts + refunds.

```sql
SELECT
  sm_store_id,
  SUM(order_gross_revenue) AS gross_revenue,
  SUM(order_discounts) AS discounts,
  SUM(order_refunds) AS refunds,
  SUM(order_net_revenue_before_refunds) AS net_revenue_before_refunds,
  SUM(order_net_revenue) AS net_revenue,
  SUM(order_net_revenue) - (SUM(order_gross_revenue) + SUM(order_discounts) + SUM(order_refunds)) AS net_check,
  SUM(order_total_revenue) AS total_revenue,
  SUM(order_net_duties) AS duties_not_in_total
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY sm_store_id
ORDER BY net_revenue DESC
```

`net_check` is 0 up to rounding.

## Channel Mapping Debug

```sql
SELECT
  sm_channel,
  sm_default_channel,
  sm_sub_channel,
  sm_order_sales_channel,
  source_system_sales_channel,
  source_system,
  COUNT(*) AS orders
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY sm_channel, sm_default_channel, sm_sub_channel, sm_order_sales_channel,
  source_system_sales_channel, source_system
ORDER BY orders DESC
LIMIT 100
```

Then sample a few orders from a surprising bucket with `sm_utm_source_medium`,
`order_discount_codes_csv`, and tags to see why they landed there.

## Multi-Touch Attribution

Only when the user asks for MTA, model comparison, or purchase journeys. Read the
schema first; it varies by enabled models.

```sql
SELECT column_name, data_type
FROM `<project>.<sm_experimental>.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'obt_purchase_journeys_with_mta_models'
ORDER BY ordinal_position
```
