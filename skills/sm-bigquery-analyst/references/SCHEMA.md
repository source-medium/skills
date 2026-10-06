# Schema Reference

Warehouse layouts, datasets, key tables, grains, and column conventions for
SourceMedium BigQuery. Metric meaning lives in `ANALYSIS_SEMANTICS.md`; SQL lives
in `QUERY_PATTERNS.md`. When this file and the live warehouse disagree, the
warehouse wins: discover with `dim_data_dictionary` and `INFORMATION_SCHEMA`.

## Warehouse Layouts

| | Dedicated warehouse (Pro) | Shared warehouse (Foundation) |
|---|---|---|
| Project | The tenant's own project, usually `sm-<something>` | `sourcemedium-bi`, shared by many tenants |
| Dataset names | `sm_transformed_v2`, `sm_metadata`, ... | `<tenant>_sm_transformed_v2`, `<tenant>_sm_metadata`, ... |
| Reached through | The SourceMedium MCP (every plan), or directly with workspace members' own Google accounts (direct warehouse access) | The SourceMedium MCP |
| Customer-owned tables | Datasets that workspace editors and admins create in the same project | Not joinable with SourceMedium data in the warehouse |
| Region | US | US |

The project id is not always `sm-<tenant id>`. Read it from the MCP's
`get_data_context` (or, with direct warehouse access, `scripts/sm_bq_doctor.py`).

Examples write `` `<project>.<sm_transformed_v2>.obt_orders` ``. Substitute the
resolved project and dataset names; on the shared warehouse every `<sm_*>`
dataset carries the tenant prefix.

## Datasets

| Dataset | What's in it | Notes |
|---------|-------------|-------|
| `<sm_transformed_v2>` | Core modeled tables: orders, order lines, customers, ads, cohorts, funnel, support, subscriptions | Foundation gets a subset; see below |
| `<sm_metadata>` | `dim_data_dictionary`, `dim_semantic_metric_catalog`, `obt_data_movement_job_logs_v1`; dedicated only: `dim_tenant_custom_objects` | Start every investigation here |
| `<sm_views>` | `rpt_order_returns_v1`, `rpt_customers_first_and_last_order_summary_v1` | Shared-warehouse tenants also have legacy views here |
| `<sm_experimental>` | `obt_purchase_journeys_with_mta_models`; dedicated only: `rpt_ad_attribution_performance_daily` | Multi-touch attribution; use only when asked |
| `sm_utils` | `dim_dates`, `currency_conversion_rates_daily`, `geo_countries` | Unprefixed on both layouts |
| `sm_sources` | Raw source tables the customer selected, personal-data columns withheld | Dedicated only, and not reachable through the MCP: needs direct warehouse access |

## Tables Only on the Dedicated Warehouse (Pro)

`dim_orders`, `dim_order_lines`, `dim_customers`, `dim_customer_addresses`,
`dim_order_discounts`, `dim_order_taxes`, `dim_order_shipping_lines`,
`dim_subscriptions`, `dim_subscribers`, `obt_subscriptions`,
`obt_subscription_charges`, `fct_subscription_charges`,
`rpt_subscriptions_performance_daily`, `rpt_subscription_signup_cohort_retention`,
`fct_orders_placed`, `obt_media_mix_performance`, `rpt_media_mix_channel_daily`.

On the shared warehouse, start from the `obt_*` table that covers the same
ground. `dim_product_variants` exists on both.

## Core Tables

| Table | Grain | Key | Use |
|-------|-------|-----|-----|
| `obt_orders` | 1 row per order | `sm_order_key` | Revenue, orders, AOV, new vs repeat, channel, attribution |
| `obt_order_lines` | 1 row per order line | `sm_order_line_key` | Product and SKU performance, margins, line-level subscription |
| `obt_customers` | 1 row per customer per store and source system | `sm_customer_key` | Acquisition, retention, subscription status |
| `rpt_executive_summary_daily` | 1 row per store, `sm_channel`, `sm_sub_channel`, date | composite | Daily KPI rollups, targets. Customer counts are allocated across channels |
| `rpt_ad_performance_daily` | Ad-level rows per day, **not unique**: sub-ad breakdowns repeat a store, source, channel, date, and `ad_id`, and `ad_id` can be NULL | none | Spend, impressions, clicks, platform-reported conversions and revenue. Always aggregate |
| `rpt_cohort_ltv_by_first_valid_purchase_attribute_no_product_filters` | 1 row per store, `sm_channel`, `sm_order_line_type`, `acquisition_order_filter_dimension`, dimension value, `cohort_month`, `months_since_first_order` | `cohort_filter_name_filter_value_month_id` | Cohort LTV and retention; see the cohort rules in `ANALYSIS_SEMANTICS.md` |
| `dim_product_variants` | 1 row per product variant | | SKU and variant attributes |

The cohort table is the only delivered `rpt_cohort_ltv_*` table.

## Other Analysis Tables

Confirm a table has data in `dim_data_dictionary` before relying on it.

| Table | Use |
|-------|-----|
| `obt_funnel_event_history` | Event-level funnel, session, page, and attribution-signal analysis |
| `rpt_funnel_events_performance_hourly` | Aggregated funnel and event monitoring |
| `fct_order_attribution_signals` | Order attribution signals and fallback-signal coverage |
| `obt_affiliate_conversions` | Affiliate conversions |
| `obt_customer_support_tickets`, `obt_customer_support_ticket_messages`, `obt_customer_support_teams` | Support ticket volume, lifecycle, messages, teams |
| `obt_inventory_positions` | Current inventory positions and SKU coverage |
| `fct_returns`, `fct_refunds_processed` | Returns and refunds; do not count return rows as orders |
| `rpt_outbound_message_performance_daily` | Email, SMS, and push campaign and flow performance |
| `obt_subscriptions`, `obt_subscription_charges`, `rpt_subscriptions_performance_daily`, `rpt_subscription_signup_cohort_retention` | Subscriptions (dedicated only) |
| `obt_media_mix_performance`, `rpt_media_mix_channel_daily` | Media mix (dedicated only) |

## Metadata Tables

| Table | Grain | Use |
|-------|-------|-----|
| `dim_data_dictionary` | 1 row per store, dataset, table, column | Table descriptions, freshness (`table_has_data`, `table_has_fresh_data_14d`, `table_last_data_date`), column null rates, distinct counts, categorical value distributions. Fold to one row per table with `GROUP BY` |
| `dim_semantic_metric_catalog` | 1 row per metric | Metric names, aliases, type, `calculation`, `has_filter`, `filter_condition`, `underlying_model`, `metric_time_expression`, `dependent_metrics`. About 200 public metrics |
| `obt_data_movement_job_logs_v1` | 1 row per publish attempt per table | When each SourceMedium table last published (`requested_model_name`, `status`, `dry_run`, `rows_written`, `created_at`) |
| `dim_tenant_custom_objects` | 1 row per object per daily snapshot | Dedicated only. Tables and views queried in the project in the last 180 days, with `origin` (`sm_owned` or `tenant_owned`). A usage inventory, not a full listing: use `INFORMATION_SCHEMA.SCHEMATA` and `TABLES` for that |

In the dictionary, `dataset_name` carries the tenant prefix on the shared
warehouse. Match it with `ENDS_WITH(dataset_name, 'sm_transformed_v2')`, never
with equality to the unprefixed name.

## Key Column Conventions

| Column | Notes |
|--------|-------|
| `sm_store_id` | Store identifier. A tenant can have several stores in the same tables. Discover values before filtering |
| `source_system` | Platform the record came from (for example `shopify`, `amazon`). Part of order and customer identity |
| `sm_order_key` | SourceMedium's order surrogate key: a hash of store, source system, and platform order id |
| `order_id` | The platform's order id. Unique only together with `sm_store_id` and `source_system` |
| `sm_customer_key` | Customer surrogate key: a hash of store, source system, and platform customer id. The same person on two platforms has two keys. Guest checkouts with no `customer_id` collapse into one key per store and source |
| `customer_id` | The platform's customer id; NULL for guest checkouts |
| `customer_email_hashed` | `TO_BASE64(SHA256(LOWER(TRIM(email))))`: base64, not hex |
| `is_order_sm_valid` | Valid-order flag. False for voided, cancelled, uncollectible, draft, and fully refunded orders, and for any `sm_channel` other than `online_dtc`, `amazon`, `tiktok_shop`, `retail`, `wholesale`. See `ANALYSIS_SEMANTICS.md` |
| `sm_valid_order_index`, `sm_valid_order_sequence` | Position among a customer's valid orders (`1st_order`, `repeat_order`); NULL on invalid orders. Use these for new vs repeat |
| `order_sequence` | Position among all of a customer's orders, valid or not. Not the new-customer definition |
| `sm_channel` | Sales channel; values in `ANALYSIS_SEMANTICS.md` |
| `order_processed_at_local_datetime` | Store-local order date for reporting |
| `customer_first_order_id`, `customer_last_order_id` | On `obt_customers`; computed over all orders, not valid orders only |

## Date and Time

- `*_at` columns are UTC TIMESTAMPs; `*_local_datetime` columns are store-local
  DATETIMEs. Report on the local columns.
- Compare through `DATE()`: `DATE(order_processed_at_local_datetime) BETWEEN start AND end`.
  A raw DATETIME compared to a DATE is allowed but reads the DATE as midnight, so
  an end bound silently drops the last day. A TIMESTAMP compared to a DATE is a
  type error.
- Catalog order metrics date by
  `DATE(COALESCE(order_processed_at_local_datetime, order_created_at_local_datetime))`
  (the metric's `metric_time_expression`). Valid orders carry a processed time,
  so `DATE(order_processed_at_local_datetime)` gives the same days for them.

## String Normalization

Twenty-two categorical columns are normalized when published: lowercased,
trimmed, a leading ordinal such as `1. ` removed, `sub.` shortened to `sub`, and
runs of spaces or hyphens turned into `_`. They include `sm_channel`,
`sm_sub_channel`, `sm_default_channel`, `sm_order_type`, `subscriber_status`,
`sm_order_sales_channel`, `order_sequence`, `subscription_order_sequence`,
`source_system`, `ad_campaign_type`, `ad_campaign_tactic`,
`acquisition_order_filter_dimension`, and `sm_order_line_type`.

Everything else keeps its source spelling: UTM fields, campaign and product
names, `sub_channel` on the ad table, and the cohort table's
`acquisition_order_filter_dimension_value`. Normalization follows the source
column, so a few tables publish `sm_channel` unnormalized (`'Online DTC'`):
`rpt_outbound_message_performance_daily` and
`rpt_subscriptions_performance_daily`. Always read real values with
`SELECT DISTINCT` before writing a filter constant.

## Column Names That Do Not Exist

These names appear in SourceMedium's internal models or older docs but not in
the customer tables:

| Wrong | Correct |
|-------|---------|
| `smcid` | `sm_store_id` |
| `channel` | `sm_channel` |
| `order_date` | `DATE(order_processed_at_local_datetime)` |
| `churned_subscription_count` | `cancelled_subscription_count_daily_snapshot` |
| `churned_subscriber_count` | `cancelled_subscriber_count_daily_snapshot` |
| `primary_product_image` | `primary_product_image_url` |
| `order_referring_site` | `order_referrer_url` |
| `valid_order_sequence` | `sm_valid_order_sequence` |
| `first_order_id` (on `obt_customers`) | `customer_first_order_id` |

`sm_marketing_channel` is not on `obt_orders` (use `sm_channel`), but it does
exist on `fct_order_attribution_signals`.

## Documentation Links

| Topic | URL |
|-------|-----|
| Warehouse overview (Foundation and Pro) | https://docs.sourcemedium.com/data-activation/managed-data-warehouse/overview |
| BigQuery Essentials | https://docs.sourcemedium.com/onboarding/analytics-tools/bigquery-essentials |
| SQL Query Library | https://docs.sourcemedium.com/data-activation/template-resources/sql-query-library |
| Orders Table | https://docs.sourcemedium.com/data-activation/data-tables/sm_transformed_v2/obt_orders |
| Customers Table | https://docs.sourcemedium.com/data-activation/data-tables/sm_transformed_v2/obt_customers |
| Order Lines Table | https://docs.sourcemedium.com/data-activation/data-tables/sm_transformed_v2/obt_order_lines |
| LTV Cohort Table | https://docs.sourcemedium.com/data-activation/data-tables/sm_transformed_v2/rpt_cohort_ltv_by_first_valid_purchase_attribute_no_product_filters |
| Ad Performance Table | https://docs.sourcemedium.com/data-activation/data-tables/sm_transformed_v2/rpt_ad_performance_daily |
| Data Dictionary | https://docs.sourcemedium.com/data-activation/data-tables/sm_metadata/dim_data_dictionary |
| Metric Catalog | https://docs.sourcemedium.com/data-activation/data-tables/sm_metadata/dim_semantic_metric_catalog |
| MCP connection | https://docs.sourcemedium.com/ai-analyst/connect-an-ai-assistant |
| MTA Overview | https://docs.sourcemedium.com/mta/mta-overview |
