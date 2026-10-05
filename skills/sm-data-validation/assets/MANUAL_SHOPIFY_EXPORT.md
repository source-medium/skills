# Exporting Shopify data for a SourceMedium validation

These steps produce the file your assistant needs to check a SourceMedium
number against Shopify. Option A is preferred because it uses the same
engine as Shopify's Analytics dashboards, so it matches the figures you see
there. Use Option B only if you cannot open Analytics explorations on your
plan or permissions.

You will not be asked for passwords, API keys, or customer details. A CSV
of order ids and amounts is enough.

## Before you start

Have these ready; your assistant needs them to compare like with like:

- The store (admin handle), if you have more than one.
- The date range you are asking about, start and end.
- Where the number you are questioning came from (which Shopify report or
  dashboard, and whether POS sales were excluded).

## Option A: Analytics exploration (preferred)

1. In Shopify admin, open **Analytics**, then **Reports**, then **New
   exploration** (top right).
2. Delete whatever is in the query editor and paste this, replacing the two
   dates. Use the day **before** your start date and the day **after** your
   end date; your assistant needs the extra day on each side.

   ```
   FROM sales
     SHOW gross_sales, discounts, sales_reversals, net_sales, shipping_charges, taxes, total_sales, orders
     GROUP BY order_id, order_name
     TIMESERIES day
     SINCE 2026-07-26 UNTIL 2026-08-03
     ORDER BY day ASC
     LIMIT 100000
   ```

   Do not add any filters, even if the number you are questioning left out
   point-of-sale orders. Your assistant compares every order and accounts
   for that afterwards.

   If the editor underlines a word in red, start typing it again and pick
   the suggestion it offers.

3. Run the query (the Run button, or Ctrl+Enter / Cmd+Enter). Wait for the
   table to fill.
4. Glance at the totals row. It will be higher than a figure that excluded
   point-of-sale orders, which is expected. Only change the dates if the
   window is wrong.
5. Click the **three dots** menu at the top right (next to "New
   exploration"), choose **Export**, select **CSV** and **All results from
   the data query**, then **Export**.
6. Send the downloaded CSV to your assistant, along with the exact query
   you ran. Rename it first if you exported several stores; the default
   file names look alike.

## Option B: Orders page export (fallback)

This export is organized by order **creation** time and lists one row per
line item, so it is less exact. Your assistant will account for that.

1. In Shopify admin, open **Orders**.
2. Set the date filter to your range plus one extra day on each side. Leave
   the status filters alone (include everything).
3. Click **Export** (top right). Choose **Selected orders** or **Orders by
   date**, format **Plain CSV file**, and export.
4. Shopify emails larger exports; download the file when it arrives.
5. Send the CSV to your assistant and say it came from the Orders page.

## What happens next

Your assistant pulls the same orders from your SourceMedium warehouse,
matches them order by order, and reports every difference with its cause.
Typical causes are a timezone setting, a cancelled or test order, a refund
booked on a different day, or point-of-sale orders counted on one side
only. You will get a short report with the numbers, the explanation, and a
recommendation.
