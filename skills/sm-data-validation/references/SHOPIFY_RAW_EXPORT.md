# Shopify Raw Export

How to get Shopify's own numbers at order grain, what those numbers mean,
and how they map to SourceMedium columns. Two export kinds exist; prefer the
first.

| Export | Grain | Matches the number operators quote? | Net sales exact? |
|---|---|---|---|
| ShopifyQL `sales` exploration (Analytics) | one row per order (with `GROUP BY order_id`) | yes, it is the same engine as the Analytics dashboards | yes |
| Admin Orders page CSV | one row per **line item** | no, it is a different basis (created time, includes test and unpaid) | approximate |

## Shopify Analytics semantics

These definitions are Shopify's, from its sales-report and ShopifyQL schema
pages (links at the end of this file). They decide what you can compare to
what. Where a statement comes from observation rather than the docs, it
says so.

- **Gross sales** = product price × quantity, before discounts. Excludes
  taxes, shipping, duties, and fees. Selling a gift card product is excluded
  from every sales report; paying with a gift card is included at full value.
- **Discounts** = line and order discounts, shown **negative** in ShopifyQL
  output (observed on live rows; the docs state the sign only for reversals).
- **Sales reversals** (`sales_reversals`; `returns` and the whole `*_returns`
  metric family are deprecated since 2026-10 and still run with a warning) =
  value removed through refunds, returns, cancellations, or edits, shown
  **negative** on the day the reversal was processed, under the original
  order id. A refund of an order sold before the window therefore shows up
  as its own row with gross 0 and `orders` 0. A refund that is still pending
  can show as a positive amount until it completes.
- **Net sales** = gross sales − discounts − sales reversals (with the signs
  above, gross + discounts + reversals).
- **Shipping charges**, **taxes**, **duties**, **additional fees**: separate
  columns (`shipping_charges`, `taxes`, `duties`, `additional_fees`, all
  verified 2026-10-05), each net of their own refunds. On a reversal row the
  tax column goes negative too.
- **Total sales** = net sales + taxes + duties + shipping charges + fees.
- **Day** = the day the sale happened, in the store's timezone (ShopifyQL
  also has a `TIMEZONE` modifier that overrides it). The docs do not name
  the timestamp; on live rows the day equalled the date of
  `order_processed_at` in the store timezone, and for ordinary checkout
  orders processed and created time are seconds apart. The Orders page
  export, by contrast, carries `Created at`.
- Test orders are excluded. Draft orders appear once converted into orders.
  Open, archived, pending, and cancelled orders are all included: a
  cancelled order keeps its gross sale and gets a `sales_reversals` of the
  same amount, so it reports net 0 with `orders` = 1 (verified 2026-10-05 on
  POS and online cancellations, refunded and voided alike). SourceMedium
  marks the same order `is_order_sm_valid = FALSE` with the refund attached,
  so the two sides differ by one order and zero net. An order edited after
  its day shows the edit on the edit day.
- `WHERE is_pos_sale = false` is valid ShopifyQL, and it is the filter behind
  most POS-excluded dashboard figures. This skill never puts it, or any other
  filter, on the export: the comparison is every order against every order,
  and scope differences are classified by the comparator afterwards.

SourceMedium's `obt_orders` equivalents, with the sign convention matching:

| ShopifyQL `sales` | `obt_orders` | Note |
|---|---|---|
| `order_id` | `order_id` | Shopify numeric id; SM stores it as a string |
| `order_name` | `order_name` | `#1001` style; fallback match key only. Names repeat across a brand's stores with different ids, so never match on name across stores |
| `day` | `DATE(order_processed_at_local_datetime)` | only equal when the two store timezones agree |
| `gross_sales` | `order_gross_revenue` | |
| `discounts` | `order_discounts` | both negative |
| `sales_reversals` | `order_refunds` | both negative; Shopify books on the refund day, SM on the order, so by-day views drift |
| `net_sales` | `order_net_revenue` | gross + discounts + refunds on both sides |
| `shipping_charges` | `order_net_shipping` | |
| `taxes` | `order_total_taxes` | |
| `total_sales` | `order_total_revenue` | compare only after net matches |
| `orders` | `COUNT(*)` | 0 on a return-only row; the comparator uses this to recognize prior-period refunds |

## ShopifyQL queries

Files live in `assets/shopifyql/`. Replace the dates; keep the padding.

### Sales by order (primary)

```
FROM sales
  SHOW gross_sales, discounts, sales_reversals, net_sales, shipping_charges, taxes, total_sales, orders
  GROUP BY order_id, order_name
  TIMESERIES day
  SINCE 2026-07-26 UNTIL 2026-08-03
  ORDER BY day ASC
  LIMIT 100000
```

- `SINCE`/`UNTIL` are inclusive; this example pads 2026-07-27..08-02 by one
  day each side.
- No `WHERE` clause, whatever filters the operator's report had. If their
  figure came from a POS-excluded report, reproduce that figure with the
  comparator's `--basis exclude-pos` flag; the order-level verdict always
  comes from the unfiltered run.
- Always export; never read the on-screen table as the dataset. The page
  renders a capped preview (about 1,400 rows on the store checked) and tells
  you to export for the rest. Without `LIMIT` a query returns 1,000 rows;
  `LIMIT 100000` was accepted on a live store, and the docs state no maximum,
  so if a window has more orders than that, split the window or page with
  `LIMIT count OFFSET count`.
- Verified 2026-10-05 against a live store: the query runs as written and
  returns order-grain rows. `TIMESERIES day` backfills empty days, which is
  why a placeholder row per empty day appears (`Order ID` and `Order name`
  read `None`, all amounts 0); the comparator drops those. `GROUP BY ..., day`
  is also documented and omits empty days; either is fine. `WHERE order_name
  = '#1001' OR order_name = ...` works for spot checks of specific orders.
- The schema has no `sale_kind`; return-only rows are recognized by
  `orders` = 0. Dimensions that do exist and are useful for spot checks:
  `is_sales_reversal`, `is_canceled_order`, `line_type`, `refund_id`,
  `sale_id`, `is_pos_sale`. If a future editor rejects a name, use its
  autocomplete; that list is authoritative for the store.

### Sales by day (layer 2 cross-check)

```
FROM sales
  SHOW gross_sales, discounts, sales_reversals, net_sales, total_sales, orders
  TIMESERIES day
  SINCE 2026-07-26 UNTIL 2026-08-03
  ORDER BY day ASC
```

Its totals equal the Analytics overview for the same window with no
filters applied. A POS-excluded dashboard figure will be lower; that gap is
the POS orders, which the order-grain comparison matches individually.

## Vector 2: driving the browser

Works with any browser automation that shares the operator's logged-in
Shopify admin session (Claude in Chrome, a CDP-attached browser, Playwright
connected over CDP). It does not work headless with copied cookies; Shopify
admin sessions do not survive that reliably.

1. **Navigate with the query in the URL.** The exploration page auto-runs a
   URL-encoded query (undocumented by Shopify, verified working 2026-10-05):
   `https://admin.shopify.com/store/<handle>/analytics/reports/explore?ql=<urlencoded ShopifyQL>`
   The `<handle>` is the store's admin subdomain, which can differ from the
   brand name. Ask if unsure; never guess a handle, it may belong to a
   different store.
2. **Wait for hydration.** 10 to 15 seconds after navigation. Export clicks
   fire silently into nothing on a half-loaded page.
3. **Verify the result before exporting.** Read the totals row. It should
   land near the operator's quoted number unless their report excluded POS;
   if it is far off, the window or the store handle is wrong, so fix that
   before exporting anything.
4. **Export.** The horizontal three-dots menu (top right, next to "New
   exploration") → Export → CSV. Shopify documents CSV, XML, JSONL, and
   Parquet; pick CSV and the full-results option when the dialog offers a
   choice between the current page and all rows. The file name is Shopify's
   report title plus the dates; rename it immediately to
   `<store>_<start>_<end>_sales_by_order.csv` because names collide across
   stores.
5. **Confirm the file on disk** and its row count before moving on.

Traps:

- A 2FA challenge can appear on first admin navigation. Stop and ask the
  human to complete it; do not attempt to bypass it.
- The query editor is CodeMirror with `contenteditable="false"`; typing into
  it does not work. Use the URL parameter, or dispatch a paste event, then
  Ctrl+Enter to run.
- Browser downloads may need a trusted click. If an export silently does not
  land, click the Export button with a real pointer action rather than a
  scripted `.click()`.
- Keep each automation step under the tool's timeout; Shopify pages are
  heavy.
- If the operator belongs to several stores (agency or multi-brand), confirm
  the handle matches the `sm_store_id` you are extracting from SourceMedium.
  A cross-store comparison looks exactly like a 100% discrepancy.

## Vector 3: the admin Orders CSV

When the human cannot open Analytics explorations (plan or permission), the
Orders page export is the fallback. `assets/MANUAL_SHOPIFY_EXPORT.md` has
the human-facing steps. Know its shape before you trust it:

- **One row per line item.** Shopify documents that additional line items
  sit on separate rows with "many of the fields" left blank. In practice the
  order-level columns (`Financial Status`, `Subtotal`, `Shipping`, `Taxes`,
  `Total`, `Discount Amount`, `Refunded Amount`, `Created at`,
  `Cancelled at`, `Source`, `Tags`) appear on the **first** row of each
  order and `Name` on every row. The comparator collapses on `Name` and
  takes the first non-empty value, so it is robust either way.
- **Dated by `Created at`** ("when the order was completed by the
  customer"). SourceMedium uses processed time. For most orders they are
  seconds apart; for draft orders completed later, pending-payment orders,
  and some POS flows they are not.
- **Includes everything**: test orders (Shopify says so explicitly),
  cancelled orders (`Cancelled at`), POS and draft orders (`Source`), and
  unpaid orders (`Financial Status`). That is what we want. The comparator
  uses `Financial Status` and `Cancelled at` to explain rows and compares
  POS orders like any other unless `--basis exclude-pos` is passed to
  reproduce a quoted figure.
- **It is a different measure from the Sales report.** Shopify: the Sales
  report shows goods exchanged, the export shows each order's current
  total. A custom (non-line-item) refund appears in `Refunded Amount` but
  not as a sales reversal.
- **Money columns** mirror the Order API fields: `Lineitem price` is the
  unit price before discounts; `Subtotal` is the sum of line prices after
  discounts and before returns (and includes tax when the store prices
  tax-inclusive); `Discount Amount` is the order's total discounts, line and
  order level; `Refunded Amount` is the sum of refund transactions, so it
  covers product, shipping, tax, and any custom amount. Hence
  gross = Σ(price × quantity), discounts = −`Discount Amount`, and
  net ≈ `Subtotal` − `Refunded Amount`, which is **approximate** whenever a
  refund included shipping or tax, and off by the tax on tax-inclusive
  stores. The report flags this; loosen the per-order tolerance to the
  shipping-plus-tax magnitude for refunded orders only. If a residual
  depends on this approximation, get the ShopifyQL export instead of
  arguing about it.
- **Currency**: `Currency` is the store's base currency at the time of the
  order, so every amount in the export is in shop currency. Compare with
  the SM `order_*` columns when SourceMedium's canonical currency is the
  shop currency, otherwise with `order_original_*`.

## Field detection in the comparator

`scripts/sm_reconcile_orders.py` normalizes headers (lowercase, non-
alphanumerics to `_`) and recognizes these aliases. If a store's export uses
a label not listed, pass `--shopify-map "<label>=<field>"`.

| Field | Accepted headers |
|---|---|
| `order_id` | `order_id`, `id` |
| `order_name` | `order_name`, `name`, `order` |
| `day` | `day`, `date`, `created_at`, `processed_at` |
| `gross` | `gross_sales` |
| `discounts` | `discounts`, `discount_amount` |
| `returns` | `sales_reversals`, `returns`, `refunds`, `refunded_amount` |
| `net` | `net_sales` |
| `shipping` | `shipping_charges`, `shipping` |
| `taxes` | `taxes`, `tax` |
| `total` | `total_sales`, `total` |
| `subtotal` | `subtotal` (Orders CSV only) |
| `lineitem_price`, `lineitem_quantity` | Orders CSV only |
| `financial_status`, `cancelled_at`, `source`, `currency` | Orders CSV only |

A `WITH TOTALS` row, a trailing summary row, or a `TIMESERIES` placeholder
row is dropped automatically when its order id is empty or reads `Total`
or `None`.

## Sources

- Sales report definitions: https://help.shopify.com/en/manual/reports-and-analytics/shopify-reports/report-types/default-reports/sales-report
- Sales discrepancies (test orders, export vs report, pending refunds): https://help.shopify.com/en/manual/reports-and-analytics/discrepancies/sales-discrepancies
- ShopifyQL `sales` schema (metrics, dimensions, deprecations): https://shopify.dev/docs/api/shopifyql/latest/schemas/sales_revenue/sales
- ShopifyQL syntax, `TIMESERIES`, `GROUP BY`, `LIMIT`: https://shopify.dev/docs/api/shopifyql/latest/syntax and https://help.shopify.com/en/manual/reports-and-analytics/shopify-reports/report-types/shopifyql-editor/shopifyql-syntax
- Exporting reports: https://help.shopify.com/en/manual/reports-and-analytics/shopify-reports/report-types/custom-reports/export-reports
- Exporting orders (CSV columns, email threshold): https://help.shopify.com/en/manual/fulfillment/managing-orders/exporting-orders
- Order API fields the export mirrors: https://shopify.dev/docs/api/admin-rest/latest/resources/order
