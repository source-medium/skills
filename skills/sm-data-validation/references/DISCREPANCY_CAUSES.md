# Discrepancy Causes

The ladder. Ordered by how often each rung is the whole answer in practice.
For each rung: what it looks like, how to detect it, how to quantify it, and
what to say. Climb from the top; most validations end on the first three.

Quantify every rung with orders and currency, then put it in the
attribution table. A rung that is ruled out is reported as ruled out, with
the check that ruled it out.

## 1. Store timezone differs between Shopify and SourceMedium

**Looks like:** daily totals differ in both directions, largest on the
first and last day of the window; the window total differs by the value of
a few hours of orders; order-by-order everything matches.

**Detect:** the offset query in `COMPARISON_PROTOCOL.md` against the
Shopify store timezone (Settings > General). Comparator shows `day-shift`
rows concentrated at window edges.

**Quantify:** re-run the comparator with `--shopify-utc-offset <shopify
offset>`; the `day-shift` class should fall to zero and the total delta with
it.

**Say:** SourceMedium is configured to report this store in `<SM tz>` while
Shopify reports in `<Shopify tz>`. Daily and weekly totals will always
differ by boundary orders until one of them changes. Recommend aligning the
SourceMedium store timezone (a configuration change, requested through
support) if the operator wants the dashboards to match Shopify day for day.

## 2. Created time versus processed time

**Looks like:** a handful of orders sit on different days; those orders are
drafts completed later, orders whose payment was captured later, or POS
orders. The Orders CSV (created time) shows this; the ShopifyQL export
(processed time) mostly does not.

**Detect:** for `day-shift` orders, compare `order_created_at` with
`order_processed_at` in the SM extract.

**Say:** Both Shopify Analytics and SourceMedium use processed time. The
Orders page export does not. Compare on processed time or accept the drift.

## 3. Valid-order definition

**Looks like:** Shopify counts more orders and more gross; SM's missing
orders are cancelled, voided, fully refunded, declined, or test.

**Detect:** comparator class `sm-invalid`. For each, `order_cancelled_at`
and `order_cancellation_reason` in the SM extract explain most; Shopify's
`Financial Status` (Orders CSV) explains the rest.

**Say:** `is_order_sm_valid` deliberately removes orders that are not real
sales. Shopify Analytics keeps the sale and books a return later. Over a
long window the net effect converges; in a short window it does not. Both
tools are applying their own definition correctly. If the operator wants Shopify's
convention, they can query SM without the validity filter; say what that
would include.

## 4. Channel scope: POS, draft, and excluded orders

**Looks like:** SM lower than Shopify by a stable share; or the reverse when
the Shopify report excluded POS and the SM query did not.

**Detect:** comparator class `sm-channel` (`draft_orders`, `excluded`). POS
orders match on both sides in the default run; `channel-basis` appears only
when `--basis exclude-pos` was used to reproduce a POS-excluded figure.
Check the config: the
`sm-exclude-order` tag and the customer's channel overrides route orders to
`excluded`, and the Executive Summary and LTV tables omit `excluded`
entirely.

**Say:** which bucket holds the orders and why (tag, override, POS). If the
operator did not know an exclusion rule existed, that is the finding.

## 5. Refund attribution and partial refunds

**Looks like:** gross and discounts match, net differs; by day, Shopify
shows negative returns on days with no corresponding SM movement.

**Detect:** comparator classes `refund-attribution` (same order, refund on
one side only) and `prior-period-return` (a Shopify row with `orders` = 0,
the refund of an order sold before the window). Compare `order_refunds`
with Shopify `sales_reversals` for those order ids; look at `latest_refund_date` in
`obt_orders` if more detail is needed.

**Say:** Shopify books a return on the refund day; SM restates the original
order. A week that contains refunds of earlier orders will always differ on
net between the two, in opposite directions at the start and end of the
window. Order-grain totals over the same order set agree.

## 6. Freshness and publish lag

**Looks like:** the last day or two of the window are low or empty in SM;
`missing-in-sm` rows are all recent.

**Detect:** `table_last_data_date` for `obt_orders` in
`dim_data_dictionary`, compared with the window end. Then the SM extract's
max `order_processed_at`.

**Say:** SourceMedium publishes on a schedule; orders after the last publish
are not there yet. Narrow the window to the last published day and re-run.
Only if `missing-in-sm` orders are **older** than the last data date is
this a load gap rather than lag; that is an escalation with order ids.

## 7. Store and project mismatch

**Looks like:** nothing matches, or match rate is a fraction; order names
overlap but ids do not.

**Detect:** `SELECT DISTINCT sm_store_id` in the SM project versus the
Shopify handle that produced the export. Multi-store tenants and agencies
hit this.

**Say:** the export and the extract are from different stores. Redo with
the right pair. Never continue a comparison across stores.

## 8. Currency

**Looks like:** every amount differs by a near-constant ratio.

**Detect:** `order_currency_code` versus the Shopify export currency.
Multi-currency stores: compare `order_original_*` columns.

**Say:** SM canonicalizes to one reporting currency; Shopify reports in the
store currency. State the rate behavior and compare like with like.

## 9. Order edits and line-basis differences

**Looks like:** `gross-delta` on a few orders; the order was edited after
placement (items added or removed), or includes a tip, a gift card product,
or a 100% discounted line.

**Detect:** per-order deltas in `matched_deltas.csv`; open the order in
Shopify admin (vector 2 or the human) and look at the timeline.

**Say:** which orders, what changed, and when. If SM reflects the
pre-edit state and the edit is older than the last publish, that is an
escalation; if the edit is newer, it is rung 6.

## 10. Shipping, tax, and duties inclusion

**Looks like:** net matches, total differs; or the operator is comparing
Shopify "Total sales" to SM `order_net_revenue`.

**Detect:** comparator class `shipping-tax-delta`; confirm which Shopify
column the operator quoted.

**Say:** the matching pairs are net to net and total to total; name the
pair the operator should use.

## 11. Discount handling

**Looks like:** `discount-basis` deltas; gross matches, discounts differ,
often on orders paid partly with gift cards or using shipping discounts.

**Detect:** per-order discount deltas; `order_discount_codes_csv` in
`obt_orders`; whether Shopify is counting a shipping discount inside
`discounts` (it is not; SM has `order_shipping_discounts` separately).

**Say:** which discount type sits on which side.

## 12. Fully discounted and zero-value orders

**Looks like:** order counts differ while revenue does not, or a reporting
view differs from `obt_orders` by a round amount.

**Detect:** orders with `order_gross_revenue > 0` and
`order_net_revenue = 0`; check whether the operator's SM number came from
an Executive Summary or a customized view that nets these out.

**Say:** which table the SM number came from and how it treats them.

## 13. Something else

If the residual survives every rung: list the order ids, the metric, both
values, and the SM extract timestamps, and escalate to SourceMedium support
with the report attached. Do not propose a mechanism you have not shown.
