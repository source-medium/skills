# Custom Data Tables

Use this reference when a user wants to analyze their own BigQuery tables
alongside SourceMedium data.

Do not edit this packaged reference for a specific operator. Look for a
project-local note such as `sourcemedium_custom_data.md`, `CUSTOM_DATA.md`, or a
user-provided warehouse README. If none exists, create one in the user's working
project from the template below before writing SQL that touches their tables.

SourceMedium tables stay the source of truth for SourceMedium metrics (orders,
revenue, LTV, customers, ad performance, attribution). Treat custom tables as
segmentation, enrichment, operational context, or inputs to a custom metric that
gets its own name.

## Where Customer Tables Live

Joining customer tables to SourceMedium data in the warehouse needs direct
warehouse access, which is part of Pro (the dedicated warehouse).

- **Dedicated warehouse (Pro)**: in datasets the customer created in the same
  project. `INFORMATION_SCHEMA.SCHEMATA` lists them;
  `<sm_metadata>.dim_tenant_custom_objects` shows which tables were used in the
  last 180 days, with `origin = 'tenant_owned'` or `'sm_owned'`. The SourceMedium
  MCP's `run_bigquery_sql` can join these datasets for direct workspace members;
  `bq` can too, and can also reach another project of the customer's in the same
  region (US).
- **Shared warehouse (Foundation)**: SourceMedium's shared project holds no
  customer tables and the plan has no direct warehouse access, so there is no
  in-warehouse join. The MCP's results (up to 500 rows) can be combined with the
  customer's own data outside the warehouse; say that is what was done.

---

## Template (copy and fill in for each table)

```
## Table: <table_name>

- **Project**: <your-gcp-project>
- **Dataset**: <your-dataset>
- **Full ref**: `<your-gcp-project>.<your-dataset>.<table_name>`
- **Grain**: One row per <entity, for example "customer", "order", "session">
- **Join key to SM data**: `<sm_join_column>` (SM) = `<your_join_column>` (this table)
- **Date coverage**: <available date range and freshness>
- **Owner/source**: <system or team that owns this table>
- **Caveats**: <nulls in the key, partial coverage, deduplication needed, etc.>
- **PII columns**: <columns containing personal data>
```

---

## Discovery: Schema of an Unknown Table

Before writing SQL against any table not in `SCHEMA.md`, inspect real schema and
values. Never guess columns, join keys, or filter constants.

```sql
-- 1. Columns and types
SELECT column_name, data_type, is_nullable
FROM `<your_project>.<your_dataset>.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = '<your_table>'
ORDER BY ordinal_position

-- 2. Size
SELECT COUNT(*) AS row_count
FROM `<your_project>.<your_dataset>.<your_table>`

-- 3. Real values of a key dimension
SELECT <dim_col>, COUNT(*) AS n
FROM `<your_project>.<your_dataset>.<your_table>`
GROUP BY <dim_col>
ORDER BY n DESC
LIMIT 30
```

---

## Join Keys to SourceMedium Tables

SourceMedium surrogate keys (`sm_order_key`, `sm_customer_key`) are hashes that
exist only in SourceMedium tables. A table that came from your own systems
carries the platform ids instead.

| Your data | Join on | SourceMedium table |
|-----------|---------|--------------------|
| Orders from the source platform | `sm_store_id`, `source_system`, `order_id` | `obt_orders`, `obt_order_lines` |
| Orders derived from SourceMedium tables | `sm_order_key` | `obt_orders`, `obt_order_lines` |
| Customers from the source platform | `sm_store_id`, `source_system`, `customer_id` | `obt_customers`, `obt_orders` |
| Customers known only by email | hashed email (below) | `obt_customers` |
| Products and SKUs | `sku` or `product_variant_id`, normalized the same way on both sides | `obt_order_lines`, `dim_product_variants` |
| Daily data | the date, against `DATE(order_processed_at_local_datetime)` | `obt_orders` |

`order_id` is unique only within a store and source system; a join on
`order_id` alone can match two platforms' orders. Guest checkouts have no
`customer_id`.

Email: `obt_customers.customer_email_hashed` is
`TO_BASE64(SHA256(LOWER(TRIM(email))))`, base64 rather than hex. Hash your side
the same way to join on it, or hash both sides yourself from `customer_email`.

---

## Joining Safely

### Step 1: Cardinality check (mandatory before any join)

```sql
-- Fan-out silently inflates every SourceMedium metric
SELECT
  COUNT(*) AS total_rows,
  COUNT(DISTINCT <join_key>) AS unique_keys,
  COUNT(*) - COUNT(DISTINCT <join_key>) AS duplicate_rows
FROM `<your_project>.<your_dataset>.<your_table>`
```

- `duplicate_rows = 0`: the join is 1:1 on that key.
- `duplicate_rows > 0`: aggregate your table to the join key first.
- If the key is PII, hash or otherwise de-identify it before presenting results.

### Step 2: Join

```sql
-- Order-level enrichment, after verifying 1:1 on (sm_store_id, source_system, order_id)
SELECT
  DATE(o.order_processed_at_local_datetime) AS order_date,
  o.sm_channel,
  SUM(o.order_net_revenue) AS net_revenue,
  SUM(c.<custom_metric>) AS custom_metric
FROM `<project>.<sm_transformed_v2>.obt_orders` AS o
JOIN `<your_project>.<your_dataset>.<your_table>` AS c
  ON o.sm_store_id = c.<store_col>
 AND o.source_system = c.<source_system_col>
 AND o.order_id = c.<order_id_col>
WHERE o.is_order_sm_valid = TRUE
  AND DATE(o.order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY order_date, o.sm_channel
ORDER BY order_date DESC

-- Fan-out-safe: collapse your side to one row per key first
WITH custom_agg AS (
  SELECT <store_col>, <source_system_col>, <order_id_col>, SUM(<metric>) AS custom_metric
  FROM `<your_project>.<your_dataset>.<your_table>`
  GROUP BY <store_col>, <source_system_col>, <order_id_col>
)
SELECT
  DATE(o.order_processed_at_local_datetime) AS order_date,
  SUM(o.order_net_revenue) AS net_revenue,
  SUM(c.custom_metric) AS custom_metric
FROM `<project>.<sm_transformed_v2>.obt_orders` AS o
JOIN custom_agg AS c
  ON o.sm_store_id = c.<store_col>
 AND o.source_system = c.<source_system_col>
 AND o.order_id = c.<order_id_col>
WHERE o.is_order_sm_valid = TRUE
  AND DATE(o.order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY order_date
ORDER BY order_date DESC
```

---

## Example: Inventory Table

```
## Table: inventory_snapshots

- **Project**: acme-corp-data
- **Dataset**: ops_warehouse
- **Full ref**: `acme-corp-data.ops_warehouse.inventory_snapshots`
- **Grain**: One row per (sku, snapshot_date)
- **Join key to SM data**: `sku` (SM obt_order_lines) = `sku` (this table)
- **Caveats**: Daily snapshots only; use snapshot_date = CURRENT_DATE() - 1 for latest.
  SKU column has mixed case; normalize with LOWER(TRIM(sku)) on both sides.
- **PII columns**: none
```

```sql
WITH latest_inventory AS (
  SELECT LOWER(TRIM(sku)) AS sku, units_on_hand, reorder_threshold
  FROM `<your_project>.ops_warehouse.inventory_snapshots`
  WHERE snapshot_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)
SELECT
  ol.product_title,
  LOWER(TRIM(ol.sku)) AS sku,
  SUM(ol.order_line_quantity) AS units_sold_30d,
  MAX(inv.units_on_hand) AS units_on_hand,
  MAX(inv.reorder_threshold) AS reorder_threshold
FROM `<project>.<sm_transformed_v2>.obt_order_lines` AS ol
LEFT JOIN latest_inventory AS inv
  ON LOWER(TRIM(ol.sku)) = inv.sku
WHERE ol.is_order_sm_valid = TRUE
  AND DATE(ol.order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY ol.product_title, LOWER(TRIM(ol.sku))
ORDER BY units_sold_30d DESC
LIMIT 50
```

---

## Example: Support Tickets Table

```
## Table: support_tickets

- **Project**: acme-corp-data
- **Dataset**: helpdesk
- **Full ref**: `acme-corp-data.helpdesk.support_tickets`
- **Grain**: One row per ticket
- **Join key to SM data**: `customer_email` (this table) to `obt_customers.customer_email`, both hashed
- **Caveats**: customer_email is PII; join on hashes, never expose raw values.
  A customer may have many tickets; pre-aggregate before joining.
- **PII columns**: customer_email, customer_name, ticket_body
```

```sql
WITH ticket_counts AS (
  SELECT
    TO_HEX(SHA256(LOWER(TRIM(customer_email)))) AS email_hash,
    COUNT(*) AS ticket_count
  FROM `<your_project>.helpdesk.support_tickets`
  WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
  GROUP BY email_hash
),
customers AS (
  -- One person can have one customer row per store and source system
  SELECT
    TO_HEX(SHA256(LOWER(TRIM(customer_email)))) AS email_hash,
    ANY_VALUE(subscriber_status) AS subscriber_status
  FROM `<project>.<sm_transformed_v2>.obt_customers`
  WHERE customer_email IS NOT NULL
  GROUP BY email_hash
)
SELECT
  c.subscriber_status,
  COUNT(*) AS customers_with_tickets,
  AVG(t.ticket_count) AS avg_tickets_per_customer
FROM customers AS c
JOIN ticket_counts AS t USING (email_hash)
GROUP BY c.subscriber_status
ORDER BY avg_tickets_per_customer DESC
```

If one person has rows with different subscriber statuses, `ANY_VALUE` picks one;
decide whether the question needs a store filter or an explicit rule instead.
