# Schema Reference

Key tables, grains, columns, and naming conventions for SourceMedium BigQuery.

## Datasets

| Dataset | What's in it |
|---------|-------------|
| `sm_transformed_v2` | Core tables — orders, customers, order lines, dimensions, reports |
| `sm_metadata` | Data dictionary, metric catalog, data quality results |
| `sm_experimental` | MTA / attribution models |

## Project Naming Convention

Customer-hosted BigQuery projects follow the pattern:

```
sm-{{tenant_id}}
```

Example: If your tenant ID is `acme-corp`, your project is `sm-acme-corp`.

```sql
-- Example fully-qualified table reference
FROM `sm-acme-corp.sm_transformed_v2.obt_orders`
```

## Multi-Store Filtering

If your brand has multiple stores (e.g., US, EU, wholesale), all stores' data lives in the same tables. Filter by store using `sm_store_id`:

```sql
-- Single store analysis
SELECT SUM(order_net_revenue) AS revenue
FROM `your_project.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND sm_store_id = 'your_sm_store_id'

-- Multi-store breakdown
SELECT sm_store_id, COUNT(*) AS orders, SUM(order_net_revenue) AS revenue
FROM `your_project.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
GROUP BY sm_store_id
ORDER BY revenue DESC
```

**Warning:** Querying without `sm_store_id` filter analyzes ALL stores' data combined. If you have multiple stores, always include this filter for single-store analysis.

## Sales Channel Filtering

`sm_channel` is a critical dimension for segmentation. Always include it in analysis to understand performance by channel:

| Channel | Description |
|---------|-------------|
| `online_dtc` | Direct-to-consumer website orders |
| `amazon` | Amazon marketplace orders |
| `tiktok_shop` | TikTok Shop orders |

```sql
-- Channel performance breakdown
SELECT sm_channel, COUNT(*) AS orders, SUM(order_net_revenue) AS revenue
FROM `your_project.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
GROUP BY sm_channel
ORDER BY revenue DESC

-- Single channel analysis
SELECT * FROM `your_project.sm_transformed_v2.obt_orders`
WHERE is_order_sm_valid = TRUE
  AND sm_channel = 'online_dtc'
```

Channel values are derived from a hierarchy: exclusion tags → config sheet overrides → default logic (amazon/tiktok_shop/walmart.com → marketplace; pos/leap → retail; wholesale tags → wholesale; otherwise online_dtc).

## Core Tables

| Table | Grain | Primary key | Use case |
|-------|-------|-------------|----------|
| `obt_orders` | 1 row per order | `sm_order_key` | Revenue, profitability, channel analysis |
| `obt_order_lines` | 1 row per line item | `sm_order_line_key` | Product performance, margins, COGS |
| `obt_customers` | 1 row per customer | `sm_customer_key` | Acquisition, retention, subscription status |
| `dim_orders` | 1 row per order | — | Order dimension lookups |
| `dim_order_lines` | 1 row per line item | — | Product/SKU lookups |
| `dim_product_variants` | 1 row per variant | — | SKU/variant details |
| `dim_customers` | 1 row per customer | — | Customer dimension lookups |
| `rpt_executive_summary_daily` | 1 row per date | — | Daily KPI rollups |
| `rpt_ad_performance_daily` | 1 row per channel/date | — | Ad spend, impressions, clicks, conversions |
| `rpt_cohort_ltv_*` | 1 row per cohort x month x order_line_type | — | LTV analysis (see QUERY_PATTERNS.md) |

## Key Column Conventions

| Column | Notes |
|--------|-------|
| `sm_store_id` | Store identifier. One value per project. |
| `sm_channel` | Sales channel: `online_dtc`, `amazon`, `tiktok_shop`, etc. |
| `sm_order_key` | Unique order surrogate key |
| `sm_customer_key` | Unique customer surrogate key |
| `is_order_sm_valid` | Always filter to `TRUE` for order analyses |
| `order_processed_at_local_datetime` | Use for date-based reporting (localized to store timezone) |
| `order_net_revenue` | Net revenue (gross - discounts - refunds). Most common revenue metric. |
| `order_gross_revenue` | Gross revenue (before discounts/refunds) |
| `order_total_revenue` | Comprehensive (net + shipping + taxes - duties) |

## Column Names to Avoid

These internal names do not exist in customer BigQuery tables:

| Wrong | Correct |
|-------|---------|
| `smcid` | `sm_store_id` |
| `channel` | `sm_channel` |
| `churned_subscription_count` | `cancelled_subscription_count_daily_snapshot` |
| `churned_subscriber_count` | `cancelled_subscriber_count_daily_snapshot` |
| `primary_product_image` | `primary_product_image_url` |
| `order_referring_site` | `order_referrer_url` |

## Date and Time Handling

- `*_at` columns are UTC timestamps
- `*_local_datetime` columns are localized to your store's timezone — **use these for reporting**
- When comparing a timestamp to a date, wrap it: `DATE(order_processed_at_local_datetime)`

```sql
-- Correct
WHERE DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

-- Wrong (timestamp vs date comparison)
WHERE order_processed_at_local_datetime >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
```

## String Normalization

These columns are automatically standardized (trimmed, lowercased). Use lowercase snake_case values in filters:

`sm_channel`, `sm_default_channel`, `sm_sub_channel`, `sm_order_type`, `subscriber_status`, `sm_order_sales_channel`, `order_source_name`, `order_sequence`, `valid_order_sequence`, `subscription_order_sequence`, `ad_campaign_type`, `ad_campaign_tactic`, `ad_platform_campaign_objective`, `acquisition_order_filter_dimension`, `sm_order_line_type`, `slice`, `filter_name`, `filter_value`, `source_system`, `order_session_browser_type`, `order_processing_method`, `primary_order_payment_gateway`

## Discover Schema at Runtime

Use `sm_metadata.dim_data_dictionary` to discover:
- Which tables exist and have fresh data
- Column null percentages and distinct counts
- Categorical value distributions

Use `sm_metadata.dim_semantic_metric_catalog` to discover:
- 180+ pre-defined metrics with calculations
- Metric categories (revenue, marketing, customer, etc.)
- Abbreviated names and their full equivalents (aov, mer, cac, roas)

## Documentation Links

| Topic | URL |
|-------|-----|
| BigQuery Essentials | https://docs.sourcemedium.com/onboarding/analytics-tools/bigquery-essentials |
| SQL Query Library | https://docs.sourcemedium.com/data-activation/template-resources/sql-query-library |
| Orders Table | https://docs.sourcemedium.com/data-activation/data-tables/sm_transformed_v2/obt_orders |
| Customers Table | https://docs.sourcemedium.com/data-activation/data-tables/sm_transformed_v2/obt_customers |
| Order Lines Table | https://docs.sourcemedium.com/data-activation/data-tables/sm_transformed_v2/obt_order_lines |
| LTV Cohort Table | https://docs.sourcemedium.com/data-activation/data-tables/sm_transformed_v2/rpt_cohort_ltv_by_first_valid_purchase_attribute_no_product_filters |
| Ad Performance Table | https://docs.sourcemedium.com/data-activation/data-tables/sm_transformed_v2/rpt_ad_performance_daily |
| Data Dictionary | https://docs.sourcemedium.com/data-activation/data-tables/sm_metadata/dim_data_dictionary |
| Metric Catalog | https://docs.sourcemedium.com/data-activation/data-tables/sm_metadata/dim_semantic_metric_catalog |
| MTA Overview | https://docs.sourcemedium.com/mta/mta-overview |
