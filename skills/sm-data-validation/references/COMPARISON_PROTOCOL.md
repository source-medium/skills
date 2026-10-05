# Comparison Protocol

How to compare SourceMedium with a source system so that every difference
ends up attributed to a cause. Shopify orders are the worked example; the same
layers apply to any source (see `OTHER_SOURCES.md`).

## The three layers

| Layer | Proves | Cannot prove |
|---|---|---|
| 1. Totals on an identical basis | whether a difference exists, and its size | why; whether offsetting errors hide inside |
| 2. By day | whether the difference is concentrated (boundary days = timezone or timestamp; one day = a load gap; every day = a definition) | which orders |
| 3. Order by order | which orders differ, in which metric, by how much | nothing it needs to; this is the floor |

Run all three. Report all three. Layer 3 is where causes are named.

## Basis alignment checklist

Settle every row of this table before layer 1. The comparator can align some
of them (sign, POS scope, window); the rest you align by choosing the right
source report and the right SourceMedium columns.

| Basis | Shopify Analytics (ShopifyQL `sales`) | SourceMedium `obt_orders` | Align by |
|---|---|---|---|
| Timezone | store timezone (Settings > General) | SourceMedium's configured store timezone, baked into `*_local_datetime` | compare the two; if they differ, re-bucket SM by `DATETIME(order_processed_at, '<shopify tz>')` |
| Timestamp | order processed time | `order_processed_at` / `_local_datetime` (not `order_created_at`) | use processed on both sides |
| Valid order | includes cancelled orders (gross sale plus an equal `sales_reversals`, net 0, `orders` 1), excludes test orders | `is_order_sm_valid` excludes voided, cancelled, uncollectible, draft, fully refunded, fraud/declined | pull SM unfiltered, classify invalid rows as their own cause |
| Channel scope | every channel; the export is never filtered | `sm_channel` buckets such as `online_dtc`, `retail` (POS), `wholesale`, marketplace values, and the non-sale buckets `draft_orders`, `excluded`, `exchanged` (always invalid) | compare every order; POS matches like any other, the non-sale buckets are classified as `sm-channel` |
| Currency | store currency (presentment converted) | `order_*` columns are canonical currency; `order_original_*` are as-charged | compare `order_*`; if the store currency differs from the SM canonical currency, use `order_original_*` |
| Refund attribution | `sales_reversals` booked on the refund day; attached to the original `order_id` at order grain | `order_refunds` attached to the original order and its processed day | compare at order grain; expect by-day drift |
| Shipping / tax | `shipping_charges`, `taxes` separate from net | `order_net_shipping`, `order_total_taxes` separate from net | compare net first, then total |

## Canonical SourceMedium extract

Discover before running: the exact `source_system` spelling, the
`sm_store_id` value, and `table_last_data_date` for `obt_orders`. Then run
this through `sm-bigquery-analyst`'s query helper with CSV output:

```bash
python ../sm-bigquery-analyst/scripts/sm_bq_query.py \
  --project sm-<tenant_id> --format csv --sql-file sm_extract.sql > sm_orders.csv
```

```sql
-- sm_extract.sql
-- Window is padded 2 days each side so boundary orders are present under
-- either timezone. Partition column is order_processed_at_local_datetime.
SELECT
  order_id,
  order_name,
  sm_store_id,
  sm_channel,
  is_order_sm_valid,
  order_processed_at,                  -- UTC
  order_processed_at_local_datetime,   -- SourceMedium store timezone
  order_created_at,
  order_cancelled_at,
  order_currency_code,
  order_gross_revenue,
  order_discounts,                     -- negative or zero
  order_refunds,                       -- negative or zero
  order_net_revenue,
  order_net_shipping,
  order_total_taxes,
  order_total_revenue
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE source_system = '<discovered shopify value>'
  AND sm_store_id = '<sm_store_id>'
  AND DATE(order_processed_at_local_datetime)
      BETWEEN DATE_SUB(DATE '<start>', INTERVAL 2 DAY)
          AND DATE_ADD(DATE '<end>',   INTERVAL 2 DAY)
ORDER BY order_processed_at
```

On Windows the analyst helper cannot spawn `bq.cmd` from Python (it exits
with a file-not-found error), so run the same SQL with `bq` directly; the
comparator reads both outputs the same way:

```bash
bq -q query --use_legacy_sql=false --format=csv --max_rows=100000 \n  --maximum_bytes_billed=1073741824 "$(cat sm_extract.sql)" > sm_orders.csv
```

Rules for this extract:

- No `is_order_sm_valid` filter and no `sm_channel` filter. The comparator
  classifies those rows; filtering them first converts explainable rows into
  "missing orders".
- Order ids and amounts only. Do not add email, name, or address columns.
- Dry-run first and keep the cost cap. A two-week window on one store is a
  small scan; if the dry-run says otherwise, the store filter is wrong.
- Keep the receipt (SQL plus dry-run bytes) for the report.

### Store timezone check

SourceMedium's local timestamps carry the configured offset. Measure it and
compare it with the Shopify store's timezone before trusting any by-day view:

```sql
SELECT
  DATETIME_DIFF(order_processed_at_local_datetime,
                DATETIME(order_processed_at), HOUR) AS sm_offset_hours,
  COUNT(*) AS orders
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
WHERE sm_store_id = '<sm_store_id>'
  AND DATE(order_processed_at_local_datetime)
      BETWEEN DATE '<start>' AND DATE '<end>'
GROUP BY sm_offset_hours
```

Two offsets in one window usually mean a DST change fell inside it. An
offset that does not match the Shopify store setting is the
timezone rung in `DISCREPANCY_CAUSES.md`; pass the Shopify offset to the
comparator with `--shopify-utc-offset` to re-bucket SM days and measure it.

## Raw-table variant (vector 1)

When Shopify orders already sit in a BigQuery table the operator owns, skip
the CSV and do layer 3 in SQL. Discover the raw table's grain first; raw
Shopify order tables are usually one row per order with nested line items,
while some loaders land one row per line item.

```sql
WITH sm AS (
  SELECT CAST(order_id AS STRING) AS order_id, order_net_revenue, is_order_sm_valid, sm_channel,
         DATE(order_processed_at_local_datetime) AS sm_day
  FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`
  WHERE sm_store_id = '<sm_store_id>'
    AND DATE(order_processed_at_local_datetime)
        BETWEEN DATE_SUB(DATE '<start>', INTERVAL 2 DAY) AND DATE_ADD(DATE '<end>', INTERVAL 2 DAY)
),
raw AS (
  SELECT CAST(id AS STRING) AS order_id,
         <net sales expression on the raw grain> AS raw_net,
         DATE(processed_at, '<shopify tz>') AS raw_day
  FROM `<their_project>.<their_dataset>.<raw_orders>`
  WHERE DATE(processed_at, '<shopify tz>')
        BETWEEN DATE_SUB(DATE '<start>', INTERVAL 2 DAY) AND DATE_ADD(DATE '<end>', INTERVAL 2 DAY)
    AND NOT COALESCE(test, FALSE)
)
SELECT
  COALESCE(sm.order_id, raw.order_id) AS order_id,
  sm.sm_day, raw.raw_day,
  sm.is_order_sm_valid, sm.sm_channel,
  raw.raw_net, sm.order_net_revenue,
  sm.order_net_revenue - raw.raw_net AS net_delta,
  CASE
    WHEN sm.order_id IS NULL THEN 'missing-in-sm'
    WHEN raw.order_id IS NULL THEN 'sm-only'
    WHEN sm.sm_day <> raw.raw_day THEN 'day-shift'
    WHEN NOT sm.is_order_sm_valid THEN 'sm-invalid'
    WHEN ABS(sm.order_net_revenue - raw.raw_net) > 0.01 THEN 'amount-delta'
    ELSE 'match'
  END AS class
FROM sm FULL OUTER JOIN raw USING (order_id)
ORDER BY class, order_id
LIMIT 5000
```

Run the cardinality check from `sm-bigquery-analyst`'s `CUSTOM_DATA.md` on
the raw table's `id` before this join; a line-grain raw table must be
aggregated to order grain first or every SM order fans out.

## Running the comparator

```bash
python scripts/sm_reconcile_orders.py \
  --shopify shopify_sales_by_order.csv \
  --sm sm_orders.csv \
  --window 2026-07-27 2026-08-02 \
  --out-dir ./reconcile_out
```

Useful options:

- `--window START END` — the claimed window. Rows outside it on either side
  are used for matching but excluded from totals; this is how padding works.
- `--basis all | exclude-pos` — default `all`: every order on both sides.
  `exclude-pos` exists only to reproduce a figure the operator quoted from a
  POS-excluded report; it sets SM `retail` rows and Orders-export `pos` rows
  aside as `channel-basis`. The order-level verdict comes from the default
  run.
- `--sm-day local | utc` — which SM timestamp buckets the SM day. Default
  `local`.
- `--shopify-utc-offset -7` — re-bucket SM days from `order_processed_at`
  (UTC) into the Shopify store's offset instead of SM's local datetime. Use
  this to test the timezone hypothesis: if `day-shift` collapses to zero,
  that was the cause.
- `--tolerance-order 0.01` and `--tolerance-total 1.00` — per-order and
  total tolerances in currency units.
- `--out-dir` — writes `matched_deltas.csv`, `shopify_only.csv`,
  `sm_only.csv`, and `attribution.csv` next to the report.

## Reading the output

The script's own verdict is mechanical: `reconciled` (delta within
tolerance, counts equal, no residual classes), `explained` (every
difference carries a non-residual class), or `differences-remain` (a
residual class is present). The report verdict in the output contract is
yours to assign after the ladder: `differences-remain` becomes `explained`
when a rung accounts for the residual with evidence, `defect-suspected`
when none does.

The report attributes the **net revenue** delta. By construction the
attribution rows sum exactly to the headline delta; if they do not, the
input was malformed (duplicate ids, a totals row left in) and the script
says so.

| Class | Meaning | Usual rung |
|---|---|---|
| `match` | same order, same amounts, same day | none |
| `day-shift` | same order, different day; in-window on one side only | timezone or timestamp |
| `refund-attribution` | gross and discounts equal, refunds differ | refund timing or partial refund scope |
| `prior-period-return` | Shopify row with `orders` = 0: a refund, booked on the refund day, of an order sold before the window | refund attribution |
| `discount-basis` | gross equal, discounts differ | discount allocation, gift card as discount |
| `gross-delta` | gross differs | order edit, line basis, gift card product, tip |
| `shipping-tax-delta` | net equal, total differs | shipping or tax inclusion |
| `sm-invalid` | Shopify counts it, SM marks it invalid | validity definition |
| `sm-channel` | Shopify counts it, SM buckets it `excluded`, `draft_orders`, or `exchanged` | channel scope |
| `channel-basis` | set aside by `--basis exclude-pos` only | none, by construction |
| `missing-in-sm` | Shopify has the order, SM has no row | freshness, load gap, store mapping |
| `unexplained-sm-only` | SM has a valid in-scope order Shopify did not export | export filter, store mismatch |
| `unexplained-delta` | matched, amounts differ, no pattern | escalate with ids |

Everything tagged `missing-in-sm`, `unexplained-sm-only`, or
`unexplained-delta` is the residual. Walk the ladder for it; if it survives,
the verdict is `defect-suspected` and the ids go to SourceMedium support.

## Tolerances

- Per order: 0.01 in the store currency. Anything larger comes from a
  definition or data difference; rounding never gets that far.
- Total: agree it with the operator up front, default 1.00. A total inside
  tolerance with non-zero per-order deltas is still reported as `explained`
  with the deltas listed; offsetting errors are not a match.
- Counts: zero tolerance. An order count difference always has a cause.
