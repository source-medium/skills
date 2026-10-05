# Data validation: <metric> for <store>, <start> to <end>

**Verdict:** `reconciled` | `explained` | `defect-suspected` | `inconclusive`

One sentence that a non-technical reader can act on.

## The claim

| | |
|---|---|
| Metric | net sales (Shopify "Net sales") |
| Source report | Shopify Analytics > Sales over time, POS excluded |
| Window | 2026-07-27 to 2026-08-02, Shopify store timezone America/Los_Angeles |
| Store | `<shopify handle>` = SM `sm_store_id` `<value>` |
| Stated | Shopify <amount> / <orders>; SourceMedium <amount> / <orders> |

## Basis alignment

| Basis | Shopify | SourceMedium | Aligned how |
|---|---|---|---|
| Timezone | America/Los_Angeles | America/New_York (offset −4h in window) | re-bucketed SM by UTC −7 for the by-day view |
| Timestamp | processed | `order_processed_at` | same |
| Valid order | includes cancelled, excludes test | `is_order_sm_valid` | pulled unfiltered, classified |
| Channel scope | every order (quoted figure excluded POS) | every `sm_channel` | compared unfiltered; quoted figure reproduced separately with `--basis exclude-pos` |
| Currency | USD | USD | same |
| Refund attribution | refund day | original order | compared at order grain |

## Numbers

| | Shopify | SourceMedium (aligned) | Delta |
|---|---|---|---|
| Orders | | | |
| Gross | | | |
| Discounts | | | |
| Refunds | | | |
| Net | | | |

Residual after attribution: <amount> across <n> orders.

## Attribution

| Cause | Orders | Net effect | Evidence |
|---|---|---|---|
| Timezone boundary (`day-shift`) | | | comparator §Daily; offset query |
| Valid-order definition (`sm-invalid`) | | | ids in `sm_only.csv` |
| Refund attribution | | | `matched_deltas.csv` |
| Prior-period returns (`prior-period-return`) | | | `shopify_only.csv` |
| … | | | |
| Unexplained | | | ids listed below |

## Receipts

- Acquisition vector: 2 (browser), ShopifyQL in `assets/shopifyql/sales_by_order.shopifyql` with SINCE 2026-07-26 UNTIL 2026-08-03, no filters
- SM extract: `sm_extract.sql` (below), dry-run <bytes>
- Comparator: `python scripts/sm_reconcile_orders.py --shopify … --sm … --window 2026-07-27 2026-08-02 --shopify-utc-offset -7`

```sql
-- sm_extract.sql as run
```

## Recommendation

What should change, if anything, and who does it. Configuration and
reporting-habit changes here; data defects go to SourceMedium support with
the order ids from the Unexplained row.

## Unexplained order ids

`<id>`, `<id>`, …
