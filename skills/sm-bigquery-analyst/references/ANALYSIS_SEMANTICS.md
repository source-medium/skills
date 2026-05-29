# Analysis Semantics

Use this when choosing tables, resolving metric meaning, or explaining why a
SourceMedium result may differ from another tool.

## Table Selection

- Start with `obt_*` tables for most analysis. They are business-ready one-big
  tables with common joins already handled.
- Use `dim_*` and `fct_*` tables when the question needs lower-grain entities,
  debugging, or joins that the OBT does not expose.
- Use `rpt_*` tables when the question matches a pre-aggregated reporting grain
  such as daily executive KPIs, ad performance, cohort LTV, messaging, funnel, or
  returns. Do not rebuild a report table metric from raw rows unless the user
  needs a different grain or a reconciliation.
- Use `sm_experimental` for MTA/attribution models only when the user asks for
  multi-touch attribution, model comparison, or purchase journeys.

## Metric Resolution

Before calculating a named business metric, query
`sm_metadata.dim_semantic_metric_catalog` for the metric name, preferred metric,
category, type, calculation, and dependent metrics. Legacy aliases such as `aov`,
`mer`, `cac`, `roas`, `ctr`, `cpc`, `cpm`, `cpo`, `cvr`, and `cpa` should be
resolved to their preferred metric names when available.

Common defaults:

| User says | Prefer |
|-----------|--------|
| revenue | `order_net_revenue` unless gross/total/platform revenue is explicitly requested |
| AOV | `average_order_value_net` / `SUM(order_net_revenue) / order count` |
| MER | `marketing_efficiency_ratio` = revenue / ad spend |
| ROAS | `return_on_ad_spend` = revenue / ad spend; platform ROAS uses platform-reported revenue |
| CAC / CPA | ad spend / new customers |

Always state the metric column or catalog metric used in the receipt notes.

## Revenue, Refunds, and Valid Orders

- For order-based analysis, start with `is_order_sm_valid = TRUE`.
- `order_gross_revenue`: line-item revenue before discounts/refunds.
- `order_net_revenue`: gross revenue after discounts and refunds; default for
  profitability, LTV, and most revenue analysis.
- `order_total_revenue`: net revenue plus shipping/taxes/duties components.
- Discounts and refunds are usually negative or zero. Net revenue is additive:
  `order_net_revenue = order_gross_revenue + order_discounts + order_refunds`.
- Use `ABS(SUM(order_refunds))` only when presenting refund dollars or refund
  rates as positive values; keep the raw sign when reconciling net revenue.

## Store and Channel Scope

- `sm_store_id` scopes a tenant to a specific store. Discover values before
  filtering; single-store tenants usually have one value.
- `sm_channel` is SourceMedium's primary standardized channel.
- `sm_sub_channel` is an optional secondary channel breakdown.
- `sm_default_channel` is the fallback channel before mapping overrides.
- `sm_order_sales_channel` and `source_system_sales_channel` are source-system
  inputs that can explain channel mapping.
- If channel results look wrong, debug the mapping inputs before overriding:
  `sm_channel`, `sm_sub_channel`, `sm_default_channel`,
  `sm_order_sales_channel`, `source_system_sales_channel`,
  `sm_utm_source_medium`, order tags, discount codes, SKUs, and source system.

## Subscriptions

- Use `obt_orders` for order-level subscription trends, customer retention,
  subscription order counts, and order-level LTV/cohorts.
- Use `obt_order_lines` for product-level subscription performance, mixed carts,
  free gifts, bundles, add-ons, or line-specific debugging.
- Order-level fields include `sm_order_type`, `is_subscription_order`,
  `subscription_order_sequence`, and `subscription_order_index`.
- Line-level fields include `order_line_type`, `is_order_line_subscription`,
  `subscription_order_sequence`, `subscription_order_index`, and
  `subscription_id`.

## Marketing and Attribution

- For ad platform performance, use `rpt_ad_performance_daily` and group by
  `source_system`, `sm_channel`, campaign, ad group, or ad fields that exist in
  schema discovery.
- Platform-reported ROAS uses `ad_platform_reported_revenue / ad_spend`.
  Blended MER/ROAS uses order revenue / ad spend and may require executive
  summary or joined order/ad sources depending on the question.
- For TikTok CPC, CTR, and CPM, check `ad_campaign_type`; exclude
  `ad_campaign_type = 'gmv_max'` for ordinary TikTok Ads ratios because GMV Max
  rows can carry spend without ordinary click/impression coverage.
- Before deep attribution analysis, check attribution health: UTM coverage,
  fallback signals, direct/unattributed share, click IDs, landing pages,
  referrer domains, and table freshness.

## Data Health Before Conclusions

Run a diagnostic before answering surprising results:

- Table freshness and availability from `dim_data_dictionary`.
- Store IDs and selected store scope.
- Categorical value distributions before filters.
- Null rates and distinct counts for join keys and attribution fields.
- Date coverage and timezone/local datetime column choice.
- Metric catalog definition and aliases for named metrics.
