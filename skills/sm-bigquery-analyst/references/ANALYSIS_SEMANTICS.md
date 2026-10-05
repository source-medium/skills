# Analysis Semantics

Use this when choosing tables, resolving what a metric means, or explaining why a
SourceMedium result differs from another tool. Tables and columns are in
`SCHEMA.md`; SQL is in `QUERY_PATTERNS.md`.

## Table Selection

- Start with `obt_*` tables: business-ready, with common joins already done.
- Use `rpt_*` tables when the question matches their grain (daily executive KPIs,
  ad performance, cohort LTV, messaging, funnel). Do not rebuild a report metric
  from raw rows unless the user needs a different grain or a reconciliation.
- Use `dim_*` and `fct_*` tables (mostly dedicated-warehouse only) for lower-grain
  debugging and joins the OBTs do not expose.
- Use `<sm_experimental>` only for multi-touch attribution and purchase journeys.

## Metric Resolution

SourceMedium's numbers are defined in `<sm_metadata>.dim_semantic_metric_catalog`.
Resolve a named metric there before computing it; if the SourceMedium MCP is
connected, `query_metrics` compiles the definition for you.

When `query_metrics` refuses a metric, compute it with SQL from the catalog row
and say why in the notes. A catalog whose new- and repeat-customer filters still
name `valid_order_sequence` (the customer tables publish it as
`sm_valid_order_sequence`) is refused for exactly those metrics and the CAC
built on them; use the published name, as in `QUERY_PATTERNS.md`.

Reading the catalog:

- `preferred_metric_name` resolves aliases: `aov` is `average_order_value_net`,
  `mer` is `marketing_efficiency_ratio`, `cac` and `cpa` point to
  `customer_acquisition_cost`, `roas` is `return_on_ad_spend`, `ctr` is
  `click_through_rate`. Read the alias row too: today the `cpa` row itself
  divides spend by `new_customers` (distinct customers) while
  `customer_acquisition_cost` divides by `new_customer_order_count`, so name the
  one you used.
- `metric_type` is `simple`, `ratio`, `derived`, or `cumulative`.
- `calculation` is documentation, **not runnable SQL**. A simple metric reads like
  `COUNT(sm_order_key) WHERE [filter applied]`; the actual filter is in
  `filter_condition`. Its values are in published spelling (`'1st_order'`,
  `'online_dtc'`), but some column names are internal ones that the customer
  tables rename: `valid_order_sequence` is `sm_valid_order_sequence`. Check
  every column a filter names against `INFORMATION_SCHEMA.COLUMNS` and map it
  through the renames in `SCHEMA.md`. A ratio reads `metric_a / metric_b` in
  metric names, not columns. A `CUMULATIVE_*` prefix is a marker.
- `underlying_model` and `semantic_model_name` name the table (`obt_orders`,
  `obt_customers`, `rpt_ad_performance_daily`, `obt_funnel_event_history`,
  `dim_product_variants`, `rpt_executive_summary_daily`,
  `rpt_media_mix_channel_daily`). `Multiple models` means a cross-table ratio.
- `metric_time_expression` is the date the metric is reported on.

Rebuilding a metric in SQL:

1. **Simple**: the aggregate in `calculation`, on `underlying_model`, with
   `filter_condition` (column names mapped to published ones) in the `WHERE`,
   dated by `metric_time_expression`.
2. **Ratio or derived**: resolve each metric in `dependent_metrics` the same way,
   each with its own filter and table. Aggregate each side to the reporting grain,
   join on that grain (usually date), then divide:
   `SAFE_DIVIDE(SUM(numerator), SUM(denominator))`.
3. **Never average a row-level ratio.** The mean of per-row ratios is a different,
   incorrect number. This applies to AOV, ROAS, MER, CAC, rates, and cohort LTV.
4. If `has_filter` is true but `filter_condition` is NULL, the filter could not be
   published; build each side from its dependents and say so.

State the catalog metric name, and its filter, in the receipt notes.

## Common Definitions

Confirm against the catalog; these are the definitions it carries today.

| User says | Definition |
|-----------|------------|
| revenue | `order_net_revenue` on valid orders, unless gross or total is asked for |
| orders | `COUNT(sm_order_key)` on valid orders |
| AOV | `SUM(order_net_revenue) / COUNT(sm_order_key)`, valid orders |
| new customers | `COUNT(DISTINCT sm_customer_key)` where valid, `sm_valid_order_sequence = '1st_order'`, and `sm_channel IN ('online_dtc', 'amazon', 'tiktok_shop')` |
| ad spend | `SUM(ad_spend)` on `rpt_ad_performance_daily`, dated by `date` |
| MER / ROAS | `order_net_revenue` (orders) / `total_ad_spend` (ads), each aggregated separately, then divided |
| CAC | `total_ad_spend` / `new_customer_order_count` (first valid orders in those three channels). The catalog's `cpa` row divides by `new_customers` instead |
| platform ROAS | `SUM(ad_platform_reported_revenue) / SUM(ad_spend)`: what the ad platform claims, not order revenue |

`rpt_executive_summary_daily` carries revenue and spend side by side and is a
convenient rollup, but its revenue need not reconcile exactly to `obt_orders`.
Use the catalog definition when the number must match SourceMedium reporting.

## Revenue, Refunds, and Valid Orders

- Start order analysis from `is_order_sm_valid = TRUE`; without it totals will
  not match any SourceMedium surface. It is false for orders with a voided,
  cancelled, uncollectible, draft, or fully **refunded** financial status, an
  invalid-payment cancellation, or excluded zero-value sales, and for every
  order whose `sm_channel` is not `online_dtc`, `amazon`, `tiktok_shop`,
  `retail`, or `wholesale`. So valid-order totals leave out fully refunded
  orders: a refund rate on valid orders covers partial refunds only, and the
  other channels return nothing once the flag is applied.
- `order_gross_revenue`: line price times quantity, excluding gift cards.
- `order_discounts` and `order_refunds` are stored as **negative** numbers (or 0).
- `order_net_revenue_before_refunds = order_gross_revenue + order_discounts`.
- `order_net_revenue = order_gross_revenue + order_discounts + order_refunds`.
  The default for revenue, profitability, and LTV.
- `order_total_revenue = order_net_revenue` + net shipping + net taxes + net
  shipping taxes. Duties are separate (`order_net_duties`) and not included.
- Present refunds as positive amounts with `ABS(SUM(order_refunds))`; keep the
  raw sign when reconciling net revenue.

## New vs Repeat Customers

- New customer orders: `sm_valid_order_sequence = '1st_order'`. Repeat:
  `'repeat_order'`. Both are NULL on invalid orders.
- Do not use `order_sequence` for this: it counts invalid orders too, so a
  customer whose first order was cancelled is classified differently.
- The catalog's new-customer metrics also restrict to `online_dtc`, `amazon`, and
  `tiktok_shop`.
- Customer identity is per store and source system. Guest checkouts (no
  `customer_id`) collapse into one `sm_customer_key` per store and source, so a
  distinct-customer count counts all guests as one customer, and almost every
  guest order is a `repeat_order` (only the guest key's first order is
  `1st_order`). New-customer revenue and counts therefore leave out nearly all
  guest checkouts. Say so when guest volume is material
  (`COUNTIF(customer_id IS NULL)`).

## Store and Channel Scope

- `sm_store_id` scopes to one store; a tenant can have several in the same
  tables. Discover the values; leaving the filter off combines stores.
- `sm_channel` values, as published: `online_dtc`, `amazon`, `amazon_via_shopify`,
  `tiktok_shop`, `tiktok_shop_via_shopify`, `retail`, `wholesale`, `mirakl`,
  `partners_/_affiliates`, `draft_orders`, `exchanged`, `excluded`. Each tenant
  has a subset; list them before filtering. Only `online_dtc`, `amazon`,
  `tiktok_shop`, `retail`, and `wholesale` can hold valid orders, so analyze the
  others without the valid-order flag and say so.
- How a channel is assigned, first match wins: an `sm-exclude-order` tag gives
  `excluded`; native TikTok orders give `tiktok_shop`; Shopify orders sold
  through TikTok (for a store that also has a native TikTok feed) give
  `tiktok_shop_via_shopify`; Amazon's non-Amazon sales channel gives `wholesale`;
  marketplace and retail defaults (`amazon`, `amazon_via_shopify`, `tiktok_shop`,
  `mirakl`, `retail`) are kept; otherwise the tenant's channel-mapping
  configuration applies, falling back to `sm_default_channel`.
- `sm_default_channel` is the channel before configuration overrides.
  `sm_sub_channel` is a finer breakdown from the same configuration.
  `sm_order_sales_channel` and `source_system_sales_channel` are the source
  platform's own sales-channel fields.
- When channel results look wrong, inspect those inputs, plus
  `sm_utm_source_medium`, tags, and discount codes, before overriding anything.

## Subscriptions

- `obt_orders` for order-level subscription trends: `sm_order_type`,
  `is_subscription_order`, `subscription_order_sequence`,
  `subscription_order_index`.
- `obt_order_lines` for product-level subscription work, mixed carts, bundles,
  add-ons: `order_line_type`, `is_order_line_subscription`, `subscription_id`.
- The subscription and subscriber tables are on the dedicated warehouse only;
  the shared warehouse has `subscription_master`.

## Marketing and Attribution

- Ad performance: `rpt_ad_performance_daily`, always aggregated (it is not unique
  per ad and day). Group by `source_system`, `sm_channel`, campaign, ad group,
  or ad fields.
- TikTok GMV Max rows (`ad_campaign_type = 'gmv_max'`) carry spend with NULL
  clicks and impressions. Exclude them from TikTok CPC, CTR, and CPM, and say so.
- Before deep attribution work, check health: UTM coverage, fallback signals,
  direct or unattributed share, click ids, landing pages, referrers, freshness.

## Cohort LTV

`rpt_cohort_ltv_by_first_valid_purchase_attribute_no_product_filters` is the
cohort table. Its rows multiply along four axes, and every query must pin or
sum each one:

1. `sm_order_line_type`: exactly one of `all_orders`, `one_time_orders_only`,
   `subscription_orders_only`.
2. `acquisition_order_filter_dimension`: exactly one of `no_filters` (the whole
   cohort), `source/medium`, `campaign`, `discount_code`, `sub_channel`,
   `zero_party_attribution`, `order_type_(sub_vs._one_time)`. Group by
   `acquisition_order_filter_dimension_value` to segment within it.
3. `sm_channel`: the table publishes `online_dtc` and `amazon` separately, with
   no all-channel row. Filter to one channel and say so, or sum across them.
4. `sm_store_id`: filter or sum, as for any multi-store question.

Then:

- **LTV = `SAFE_DIVIDE(SUM(cumulative_order_net_revenue), SUM(cohort_size))`**
  at the reporting grain. Never `AVG(cumulative / cohort_size)`: that averages
  channels and segments unweighted and has understated real cohorts by 11% to 15%.
- `cohort_size` is constant down a cohort's offsets. Sum it across channels,
  stores, and segments at one offset; never sum it across offsets, and never
  take its MAX, MIN, or AVG.
- `months_since_first_order` is 0-indexed: 0 is the acquisition month.
- `cohort_month` is the store-local month of the customer's first valid order in
  that channel.
- The newest offsets are partial. For an N-month LTV, keep cohorts with
  `cohort_month <= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL N + 1 MONTH)`.
- Default to a 6-month horizon when the user names none, and say so.
- Flag cohorts below a stated minimum size (SourceMedium's own assistant uses 10
  customers) instead of ranking them.
- Summarizing across cohorts: pool them, `SUM(cumulative_order_net_revenue) /
  SUM(cohort_size)` over every cohort at one offset (customer-weighted). Only if
  the user wants each cohort to count equally, compute each cohort's LTV first
  and then average those, and say so.
- `cost_per_acquisition` is per store, cohort month, and channel, repeated across
  every dimension value; it cannot be attributed to a source/medium. Take
  cohort CAC from the `no_filters` rows, weighted by `cohort_size`.
- `cumulative_order_gross_profit` (not `cumulative_gross_profit`) is the profit
  column; the quantity column is spelled `cumulative_ordered_quantiy`.

For a custom window the table does not offer, build cohorts from `obt_orders`:
valid orders, `sm_valid_order_index = 1` as the anchor, `customer_id IS NOT NULL`
to exclude guests. Expect small differences from the cohort table, which assigns
one cohort per customer per channel.

## Data Health Before Conclusions

Run a diagnostic before answering a surprising result:

- Table freshness and availability from `dim_data_dictionary`.
- Store ids and the selected store scope.
- Categorical value distributions before filters.
- Null rates and distinct counts for join keys and attribution fields.
- Date coverage, and the local datetime column used.
- The catalog definition and filter for every named metric.

If the SourceMedium MCP is connected, `get_account_health` reports connection and
pipeline problems in the customer's own vocabulary.
