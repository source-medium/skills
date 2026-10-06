# Other Sources

The protocol is the same for any source SourceMedium models: pin the claim,
align the basis, acquire raw rows at the lowest grain the source exposes,
extract SM at the same grain, match, attribute. What changes is which raw
report to pull, which SM table to extract, the match key, and the rungs that
usually win. This file is the routing table; Shopify is the only source with
a shipped comparator in v0.1, so for the rest the matching step is SQL or a
spreadsheet join, documented with the same output contract.

## Ad platforms

| Source | Raw report (vector 2 or 3) | SM table | Compare at | Rungs that usually win |
|---|---|---|---|---|
| Meta Ads | Ads Manager → Reports → export at **ad** level by **day**, with the account's timezone and attribution setting shown; or the MCP's `meta_ads_query` with resource `insights` | `rpt_ad_performance_daily` filtered to Meta's `source_system` | `date` × `ad_id`, after summing SM rows | account timezone vs SM store timezone; attribution window (7-day click / 1-day view) for conversions; platform restatements of recent days; spend currency |
| Google Ads | Reports → predefined "Ad" report by day, or Campaign report by day | same table, Google's `source_system` | `date` × `ad_id` or `date` × `ad_campaign_id`, after summing SM rows | account timezone; conversion lag (conversions restate for up to 30 days); micros vs currency units |
| TikTok Ads | Ads Manager → custom report, ad level by day; separate **GMV Max** report where enabled | same table; GMV Max rows carry `ad_campaign_type = 'gmv_max'` | `date` × `ad_id`, after summing SM rows; GMV Max is campaign grain: its `ad_id` is `gmv_max:<campaign id>` | GMV Max rows carry spend, conversions, and revenue with NULL clicks and impressions; attribution setting; account timezone |

`rpt_ad_performance_daily` is not unique at these keys: sub-ad breakdowns
repeat a date and `ad_id`, and `ad_id` can be NULL. Sum the SM rows to the
comparison grain before matching, and never deduplicate them.

Spend reconciles to the cent at ad × day once timezone and currency agree.
Conversions and revenue do not: they are modeled quantities whose attribution
window and lookback differ by tool. Validate spend exactly and conversions
within an agreed window with the attribution setting named.

## Amazon

| Claim | Raw report | SM table | Key | Rungs |
|---|---|---|---|---|
| Orders / sales | Seller Central → Reports → Business Reports → Detail Page Sales and Traffic by Date, or the All Orders report (Fulfillment) | `obt_orders` with Amazon `source_system` | `order_id` (Amazon order id) | purchase date vs ship date; marketplace timezone (reports are per marketplace); pending vs shipped status; FBA vs MFN |
| Inventory | Active Listings report, pulled the same day | `obt_inventory_positions` with Amazon's `source_system`: current state only, no history | `sku` × `inventory_location_id`, after summing SM rows | snapshot timing (`inventory_snapshot_at`); a report pulled on another day cannot match |
| Ads | Advertising console → Sponsored Products/Brands/Display reports by day | `rpt_ad_performance_daily` | `date` × `ad_campaign_id`, after summing SM rows | report timezone per marketplace; 14-day attribution; restatements |

Amazon reports are per marketplace and in the marketplace's timezone. State
which marketplace the claim covers before anything else.

## TikTok Shop

Orders export from Seller Center (Orders → Export) is line-grain like the
Shopify Orders CSV: collapse to order id first. Status timing (created,
paid, shipped, completed) is the main rung: SourceMedium dates orders by
`order_processed_at_local_datetime`, so find which Seller Center time that
matches on a few orders before comparing days.

## Subscription platforms (Recharge, Skio, and similar)

| Claim | Raw report | SM table | Key |
|---|---|---|---|
| Subscription orders / charges | platform export of charges or orders by processed date | `obt_orders` with `is_subscription_order` (every plan); `fct_subscription_charges`, `obt_subscription_charges`, `obt_subscriptions` (dedicated warehouse only) | charge id, or the Shopify order id the charge created |
| Active subscribers | platform dashboard count on a date | `rpt_subscriptions_performance_daily` (dedicated warehouse only) | date |

Rungs: whether a charge created a Shopify order yet (queued, failed, or
skipped charges never appear in `obt_orders`); subscriber status timing
(cancelled at vs effective at); snapshots taken at different times of day.

## Email and SMS (Klaviyo and similar)

Campaign and flow performance exports by day map to
`rpt_outbound_message_performance_daily`. The rung is attribution: the
platform's conversion metric uses its own attribution window; compare
receives, opens, and clicks (`message_unique_*`) exactly and treat
attributed revenue (`platform_reported_*`) as modeled. This table publishes
`sm_channel` unnormalized; read its values before filtering.

## Sessions and events (GA4)

GA4 standard reports apply thresholding and sampling; the BigQuery export
does not. Compare SM's funnel tables (`obt_funnel_event_history`) with the
GA4 BigQuery export when it exists rather than with the UI reports. Bot filtering and session timeout settings are the rungs.

## Adding a source properly

When a source becomes common enough to deserve a comparator, add to this
skill:

1. A `references/<SOURCE>_RAW_EXPORT.md` with the report, its semantics, the
   field map to SM columns, and the vector 2 and 3 procedures.
2. A query file under `assets/` for the raw side where the source has a
   query language or saved-report definition.
3. Fixtures and a QA case in `scripts/qa_sm_data_validation_skill.py`.
4. New rungs in `DISCREPANCY_CAUSES.md` only when they are not already
   covered; most sources reuse timezone, timestamp, validity, scope,
   freshness, and currency.
