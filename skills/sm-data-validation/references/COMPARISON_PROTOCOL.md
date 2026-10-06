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
| Timestamp | the day the sale happened (equalled the processed date on every live row checked) | `order_processed_at` / `_local_datetime` (not `order_created_at`) | processed on both sides; only the Orders page CSV uses created time |
| Valid order | includes cancelled orders (gross sale plus an equal `sales_reversals`, net 0, `orders` 1), excludes test orders | `is_order_sm_valid` excludes voided, cancelled, uncollectible, draft, fully refunded, fraud/declined | pull SM unfiltered, classify invalid rows as their own cause |
| Channel scope | every channel; the export is never filtered | `sm_channel` buckets such as `online_dtc`, `retail` (POS), `wholesale`, marketplace values, and the non-sale buckets `draft_orders`, `excluded`, `exchanged` (always invalid) | compare every order; POS matches like any other, the non-sale buckets are classified as `sm-channel` |
| Currency | store currency (presentment converted) | `order_*` amounts are in the order's own currency (`order_currency_code`) unless the store has currency conversion on: then `is_order_currency_canonicalized` is TRUE and they are in `order_converted_currency_code`, while `order_currency_code` still names the order's currency | compare `order_*` when not converted; when converted, compare `order_original_*` and check `order_original_currency_code` against the export's currency |
| Refund attribution | `sales_reversals` booked on the refund day; attached to the original `order_id` at order grain | `order_refunds` attached to the original order and its processed day; `latest_order_refund_date` is the date of its latest line refund, in SourceMedium's store timezone | compare at order grain; expect by-day drift |
| Shipping / tax | `shipping_charges`, `taxes` separate from net | `order_net_shipping`, `order_total_taxes` separate from net | compare net first, then total |

## Canonical SourceMedium extract

Resolve the names first. `get_data_context` reports the project and the
dataset names: the examples write lane-neutral `<project>.<sm_transformed_v2>`,
which is `<tenant>_sm_transformed_v2` in `sourcemedium-bi` on the shared
warehouse (see `sm-bigquery-analyst`, "Resolve the Warehouse Names"). Then
discover the `sm_store_id` value and `table_last_data_date` for `obt_orders`.
`source_system` is published normalized, so Shopify orders are `'shopify'`.

The window below is the worked example: a claim for 2026-07-27 to 2026-08-02,
padded one day on each side. Use the same padded window as the Shopify export.

```sql
-- sm_extract.sql
-- Timestamps are formatted as text: the MCP returns a raw TIMESTAMP as epoch
-- seconds, which the comparator refuses. order_processed_at_local_datetime is
-- the partition column.
SELECT
  order_id,
  order_name,
  sm_store_id,
  sm_channel,
  is_order_sm_valid,
  FORMAT_TIMESTAMP('%F %T', order_processed_at) AS order_processed_at,  -- UTC
  order_processed_at_local_datetime,   -- SourceMedium store timezone
  FORMAT_TIMESTAMP('%F %T', order_created_at) AS order_created_at,
  FORMAT_TIMESTAMP('%F %T', order_cancelled_at) AS order_cancelled_at,
  latest_order_refund_date,            -- latest line refund, SourceMedium store timezone
  order_currency_code,
  order_converted_currency_code,
  is_order_currency_canonicalized,
  order_gross_revenue,
  order_discounts,                     -- negative or zero
  order_refunds,                       -- negative or zero
  order_net_revenue,
  order_net_shipping,
  order_total_taxes,
  order_total_revenue
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE source_system = 'shopify'
  AND sm_store_id = '<sm_store_id>'
  AND DATE(order_processed_at_local_datetime) BETWEEN DATE '2026-07-26' AND DATE '2026-08-03'
ORDER BY order_processed_at
```

Rules for this extract:

- No `is_order_sm_valid` filter and no `sm_channel` filter. The comparator
  classifies those rows; filtering them first converts explainable rows into
  "missing orders".
- Order ids and amounts only. Do not add email, name, or address columns.
- Keep every receipt (the SQL, and the MCP receipt or the dry-run bytes) for
  the report.

### Plan the pages

Count the orders per day first. The count sizes every page and, with direct
access, `--max-rows`:

```sql
SELECT DATE(order_processed_at_local_datetime) AS day, COUNT(*) AS orders
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE source_system = 'shopify'
  AND sm_store_id = '<sm_store_id>'
  AND DATE(order_processed_at_local_datetime) BETWEEN DATE '2026-07-26' AND DATE '2026-08-03'
GROUP BY day
ORDER BY day
```

### Through the MCP (every plan)

`run_bigquery_sql` returns at most 500 rows and 256 KiB per call, and this
extract runs to about 650 bytes a row, so one call holds roughly 350 orders.

1. Run the extract once per day of the padded window: replace the `BETWEEN`
   with `= DATE '<day>'`.
2. A day with more than 300 orders in the plan, or any page that comes back
   truncated, is split by hour: add
   `AND EXTRACT(HOUR FROM order_processed_at_local_datetime) BETWEEN 0 AND 11`,
   then `BETWEEN 12 AND 23`, and halve again until every page fits.
3. Check every result before using it: `truncated` must be false, and
   `returned_rows` must equal `total_rows`. A truncated page is incomplete.
   Split it and rerun; never write it.
4. Write every page's rows to `sm_orders.csv`: one header in the extract's
   column order, then the rows with their values exactly as returned. The
   rows across all pages must add up to the plan's count. The comparator
   refuses a duplicate order id (exit 2), which catches overlapping pages.

### With direct warehouse access (Pro)

Dry-run, then run with `--max-rows` set a little above the plan's total:

```bash
python ../sm-bigquery-analyst/scripts/sm_bq_query.py \
  --project <project> --dry-run --sql-file sm_extract.sql
python ../sm-bigquery-analyst/scripts/sm_bq_query.py \
  --project <project> --format csv --max-rows <plan total + 100> \
  --sql-file sm_extract.sql > sm_orders.csv
```

Exit 7 means there were more rows than `--max-rows`: the CSV holds only the
first ones. Stop, delete it, raise `--max-rows` to cover the plan's total,
and rerun. Never run the comparator on an extract whose command exited
non-zero.

On Windows the analyst helper cannot spawn `bq.cmd` from Python (it exits
with a file-not-found error), so run the same SQL with `bq` directly. The
SQL goes on stdin: passed as an argument, its leading `--` comment is read
as a flag. `bq` stops at `--max_rows` without saying so, so set it one above
the plan's total and check the CSV has exactly that total of data rows:

```bash
bq query --use_legacy_sql=false --dry_run < sm_extract.sql
bq -q query --use_legacy_sql=false --format=csv --max_rows=<plan total + 1> \
  --maximum_bytes_billed=1073741824 < sm_extract.sql > sm_orders.csv
```

### Store timezone check

SourceMedium's local timestamps carry the configured offset. Measure it and
compare it with the Shopify store's timezone before trusting any by-day view:

```sql
SELECT
  DATETIME_DIFF(order_processed_at_local_datetime,
                DATETIME(order_processed_at), HOUR) AS sm_offset_hours,
  COUNT(*) AS orders
FROM `<project>.<sm_transformed_v2>.obt_orders`
WHERE sm_store_id = '<sm_store_id>'
  AND DATE(order_processed_at_local_datetime)
      BETWEEN DATE '2026-07-27' AND DATE '2026-08-02'
GROUP BY sm_offset_hours
```

Two offsets in one window usually mean a DST change fell inside it. An
offset that does not match the Shopify store setting is the
timezone rung in `DISCREPANCY_CAUSES.md`; pass the Shopify offset to the
comparator with `--shopify-utc-offset` to re-bucket SM days and measure it.
The offset is fixed, so across a DST change run the comparator once per side
of the change.

## Raw-table variant (vector 1)

When Shopify orders already sit in a table in the customer's dedicated
warehouse (Pro), skip the CSV and do layer 3 in SQL: through
`run_bigquery_sql` for a dataset in the dedicated project, with `bq` for
`sm_sources` or another project. Discover the raw table's grain first; raw
Shopify order tables are usually one row per order with nested line items,
while some loaders land one row per line item.

```sql
WITH sm AS (
  SELECT CAST(order_id AS STRING) AS order_id, order_net_revenue, is_order_sm_valid, sm_channel,
         DATE(order_processed_at_local_datetime) AS sm_day
  FROM `<project>.<sm_transformed_v2>.obt_orders`
  WHERE source_system = 'shopify'
    AND sm_store_id = '<sm_store_id>'
    AND DATE(order_processed_at_local_datetime) BETWEEN DATE '2026-07-26' AND DATE '2026-08-03'
),
raw AS (
  SELECT CAST(id AS STRING) AS order_id,
         <net sales expression on the raw grain> AS raw_net,
         DATE(processed_at, '<shopify tz>') AS raw_day
  FROM `<your_project>.<your_dataset>.<your_table>`
  WHERE DATE(processed_at, '<shopify tz>') BETWEEN DATE '2026-07-26' AND DATE '2026-08-03'
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

The query returns one row per order. Through `run_bigquery_sql` (500 rows a
call), total it by class first by wrapping it in
`SELECT class, COUNT(*) AS orders, SUM(net_delta) AS net_delta FROM (...) GROUP BY class`,
then read the order ids one class at a time, leaving out `match`, and split
any page that comes back truncated.

## Running the comparator

```bash
python scripts/sm_reconcile_orders.py \
  --shopify shopify_sales_by_order.csv \
  --sm sm_orders.csv \
  --window 2026-07-27 2026-08-02 \
  --quoted-shopify-net 412000 --quoted-sm-net 398000 \
  --out-dir ./reconcile_out
```

Useful options:

- `--window START END` — the claimed window, `YYYY-MM-DD`. Rows outside it
  on either side are used for matching but excluded from totals; this is how
  padding works. Shopify rows count on their own day, so the Shopify total is
  the figure Shopify shows for the window. Every Shopify row needs a day; an
  invalid date exits 2.
- `--quoted-shopify-net AMOUNT`, `--quoted-sm-net AMOUNT` — the operator's
  figures. The report shows each one's gap to what the inputs reproduce; a
  gap beyond the total tolerance keeps the verdict at `differences-remain`.
- `--basis all | exclude-pos` — default `all`: every order on both sides.
  `exclude-pos` sets SM `retail` rows aside as `channel-basis`, and with the
  Orders-page export its `pos` rows too, so there it reproduces a
  POS-excluded figure. The Analytics export has no channel column: the
  Shopify total keeps POS and the matched POS orders show as
  `channel-basis`, so it does not reproduce a POS-excluded Shopify figure.
  The order-level verdict comes from the default run.
- `--sm-day local | utc` — which SM timestamp buckets the SM day. Default
  `local`.
- `--shopify-utc-offset -7` — re-bucket SM days from `order_processed_at`
  (UTC) into the Shopify store's offset instead of SM's local datetime. Use
  this to test the timezone hypothesis: if `day-shift` collapses to zero,
  that was the cause.
- `--tolerance-order 0.01` and `--tolerance-total 1.00` — per-order and
  total tolerances in currency units.
- `--out-dir` — writes `matched_deltas.csv`, `shopify_only.csv`,
  `sm_only.csv`, `undated.csv`, and `attribution.csv` next to the report.

## Reading the output

The script's own verdict is mechanical: `reconciled` (delta within
tolerance, counts equal, no residual classes, quoted figures reproduced),
`explained` (every difference carries a non-residual class), or
`differences-remain` (a residual class is present, or a quoted figure is not
reproduced). The report verdict in the output contract is
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
| `edge-reversal` | a refund, cancellation, or edit Shopify booked across the window edge from the sale: inside the window for an order sold on a padding day, or after the window for an order sold inside it | refund attribution |
| `refund-attribution` | gross and discounts equal; SM carries more refund, dated after the export's last day (or undated) | refund timing |
| `prior-period-return` | Shopify row with `orders` = 0: a refund, booked on the refund day, of an order sold before the export | refund attribution |
| `discount-basis` | gross equal, discounts differ | discount allocation, gift card as discount |
| `gross-delta` | gross differs | order edit, line basis, gift card product, tip |
| `shipping-tax-delta` | net equal, total differs | shipping or tax inclusion |
| `sm-invalid` | Shopify counts it, SM marks it invalid | validity definition |
| `sm-channel` | Shopify counts it, SM buckets it `excluded`, `draft_orders`, or `exchanged` | channel scope |
| `channel-basis` | set aside by `--basis exclude-pos` only | none, by construction |
| `missing-in-sm` | Shopify has the order, SM has no row | freshness, load gap, store mapping |
| `unexplained-sm-only` | SM has a valid in-scope order Shopify did not export | export filter, store mismatch |
| `refund-missing-in-sm` | Shopify booked a refund for the order inside the export; SM carries less refund | freshness, else escalate |
| `refund-missing-in-shopify` | SM carries more refund, dated (`latest_order_refund_date`) inside the export, and the export does not show it | custom refund, else escalate |
| `unexplained-delta` | matched, amounts differ, no pattern | escalate with ids |
| `undated` | a row with no day: left out of the window totals and listed separately | re-export with a day on every row |

Everything tagged `missing-in-sm`, `unexplained-sm-only`,
`refund-missing-in-sm`, `refund-missing-in-shopify`, `unexplained-delta`, or
`undated` is the residual. Walk the ladder for it; if it survives, the
verdict is `defect-suspected` and the ids go to SourceMedium support. An
order can carry two classes, such as a sale that matches and a refund across
the window edge.

## What a real run looks like

On a two-day window of a returns-heavy store (2,723 export rows, 667
in-window orders), the first version of the comparator reconciled with a
zero residual: 407 exact matches, 101
`refund-attribution` (SM already carries a refund Shopify books on a later
day), 758 `prior-period-return` rows, 102 `sm-invalid` (cancelled and fully
refunded orders, plus zero-value exchange orders), 56 `sm-channel`
(`exchanged` and `excluded`), one `shipping-tax-delta`. The headline net
delta was large and entirely explained. That is the normal shape: a big
number at the top, nothing left at the bottom.

## Tolerances

- Per order: 0.01 in the store currency. Anything larger comes from a
  definition or data difference; rounding never gets that far.
- Total: agree it with the operator up front, default 1.00. A total inside
  tolerance with non-zero per-order deltas is still reported as `explained`
  with the deltas listed; offsetting errors are not a match.
- Counts: zero tolerance. An order count difference always has a cause.
