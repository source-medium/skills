# Shopify Raw Export

How to get Shopify's own numbers at order grain, what those numbers mean,
and how they map to SourceMedium columns. Two export kinds exist; prefer the
first.

| Export | Grain | Matches the number operators quote? | Net sales exact? |
|---|---|---|---|
| ShopifyQL `sales` exploration (Analytics) | one row per order (with `GROUP BY order_id`) | yes, it is the same engine as the Analytics dashboards | yes |
| Admin Orders page CSV | one row per **line item** | no, it is a different basis (created time, includes test and unpaid) | approximate |

## Shopify Analytics semantics

These definitions are Shopify's. They decide what you can compare to what.

- **Gross sales** = product price × quantity, before discounts. Excludes
  shipping, taxes, duties, tips, and gift card product sales (gift cards are
  reported as their own sale kind, not as gross sales).
- **Discounts** = line and order discounts, **negative**.
- **Sales reversals** (`sales_reversals`; the older name `returns` still runs
  but the editor flagged it deprecated on 2026-10-05) = refunded product
  value, **negative**, booked on the day the refund happened under the
  original order id. A refund of an order sold before the window therefore
  shows up as its own row with gross 0 and `orders` 0.
- **Net sales** = gross sales + discounts + sales reversals.
- **Shipping charges**, **taxes**, **duties**, **additional fees**: separate
  columns, each net of their own refunds.
- **Total sales** = net sales + shipping + taxes + duties + additional fees.
- **Day** = the order's processed time in the store's timezone
  (Settings > General > Standards and formats). Not created time.
- Test orders are excluded. Draft orders appear once completed. Cancelled
  orders keep their original sale and show the cancellation as a return when
  money was returned; verify on one known cancelled order for the store
  before relying on this, because gateway and timing details vary.
- `WHERE is_pos_sale = false` is valid ShopifyQL, and it is the filter behind
  most POS-excluded dashboard figures. This skill never puts it, or any other
  filter, on the export: the comparison is every order against every order,
  and scope differences are classified by the comparator afterwards.

SourceMedium's `obt_orders` equivalents, with the sign convention matching:

| ShopifyQL `sales` | `obt_orders` | Note |
|---|---|---|
| `order_id` | `order_id` | Shopify numeric id; SM stores it as a string |
| `order_name` | `order_name` | `#1001` style; fallback match key |
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
- The default row cap is 1,000. `LIMIT 100000` lifts it. If the store does
  more than that in the window, split the window.
- Verified 2026-10-05 against a live store: the query runs as written and
  returns order-grain rows. `sale_kind` is not a column (the editor offers
  `sale_id`), so return-only rows are recognized by `orders` = 0 rather than
  by a kind dimension. If a future editor rejects a name, use its
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
   URL-encoded query:
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
4. **Export.** Actions menu (three dots, top right, next to "New
   exploration") → Export → choose CSV and "All results from the data
   query" → Export. The file name is Shopify's report title plus the dates;
   rename it immediately to `<store>_<start>_<end>_sales_by_order.csv`
   because names collide across stores.
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

- **One row per line item.** Order-level columns (`Financial Status`,
  `Subtotal`, `Shipping`, `Taxes`, `Total`, `Discount Amount`,
  `Refunded Amount`, `Created at`, `Cancelled at`, `Source`, `Tags`) are
  populated only on the **first** row of each order; `Name` is on every row.
  The comparator collapses on `Name` and takes the first non-empty value.
- **Filtered by created time**, in the store timezone. Analytics and
  SourceMedium both use processed time. For most orders they are seconds
  apart; for draft orders completed later, pending-payment orders, and some
  POS flows they are not.
- **Includes everything**: test orders, unpaid, cancelled, POS, drafts.
  That is what we want. The comparator uses `Financial Status` and
  `Cancelled at` to explain rows and compares POS orders like any other
  unless `--basis exclude-pos` is passed to reproduce a quoted figure.
- **Money columns**: `Lineitem price` is the unit price before line
  discounts; `Subtotal` is after all discounts; `Discount Amount` is the
  order's total discounts; `Refunded Amount` is the total refunded including
  shipping and tax portions. Hence gross = Σ(price × quantity),
  discounts = −`Discount Amount`, and net ≈ `Subtotal` − `Refunded Amount`,
  which is **approximate** whenever a refund included shipping or tax. The
  report flags this and the per-order tolerance should be loosened to the
  shipping-plus-tax magnitude only for refunded orders. If a residual
  depends on this approximation, get the ShopifyQL export instead of
  arguing about it.
- **Currency**: `Currency` is the presentment currency per order. Multi-
  currency stores need the SM `order_original_*` columns for comparison.

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

A `WITH TOTALS` row or a trailing summary row is dropped automatically when
its order id is empty or reads `Total`.
