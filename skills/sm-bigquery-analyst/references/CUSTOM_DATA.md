# Custom Data Tables

Use this reference when a user wants to analyze their own BigQuery tables alongside
SourceMedium data.

Do not edit this packaged reference for a specific operator. Instead, look for a
project-local note such as `sourcemedium_custom_data.md`, `CUSTOM_DATA.md`, or a
user-provided warehouse README. If no note exists, create one in the user's working
project from the template below before writing SQL that touches their tables.

SourceMedium tables should remain the metric source of truth for SourceMedium metrics
such as orders, revenue, LTV, customers, ad performance, and attribution. Treat custom
tables as segmentation, enrichment, operational context, or custom metric inputs unless
the user explicitly defines a custom metric.

---

## Template (copy and fill in for each table)

```
## Table: <table_name>

- **Project**: <your-gcp-project>
- **Dataset**: <your-dataset>
- **Full ref**: `<your-gcp-project>.<your-dataset>.<table_name>`
- **Grain**: One row per <entity — e.g., "customer", "order", "session">
- **Join key to SM data**: `<sm_join_column>` (SM) = `<your_join_column>` (this table)
- **Date coverage**: <available date range and freshness>
- **Owner/source**: <system or team that owns this table>
- **Caveats**: <anything unusual — nulls in key column, partial date coverage, deduplication needed, etc.>
- **PII columns**: <list any columns containing personal data>
```

---

## Discovery: Schema of an Unknown Table

Before writing SQL against any table not in `references/SCHEMA.md`, inspect actual schema
and values. Never guess columns, join keys, or filter constants.

```sql
-- 1. List all columns and types
SELECT column_name, data_type, is_nullable
FROM `<project>.<dataset>.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = '<table>'
ORDER BY ordinal_position

-- 2. Check row count and rough size
SELECT COUNT(*) AS row_count
FROM `<project>.<dataset>.<table>`

-- 3. Sample key dimension values (never encode filter values without seeing real data)
SELECT DISTINCT <dim_col>, COUNT(*) AS n
FROM `<project>.<dataset>.<table>`
GROUP BY <dim_col>
ORDER BY n DESC
LIMIT 30
```

---

## Joining Custom Tables to SourceMedium Data

### Step 1: Cardinality check (mandatory before any join)

```sql
-- Run this before joining. Fan-out silently inflates every SM metric.
SELECT
  COUNT(*)                        AS total_rows,
  COUNT(DISTINCT <join_key>)      AS unique_keys,
  COUNT(*) - COUNT(DISTINCT <join_key>) AS duplicate_rows
FROM `<your_project>.<your_dataset>.<your_table>`
```

- If `duplicate_rows = 0`: join is safe (1:1 cardinality on join key)
- If `duplicate_rows > 0`: aggregate your table first, then join
- If the key contains PII, hash or otherwise de-identify it before presenting results

```sql
-- Safe join pattern (after verifying 1:1 cardinality)
SELECT
  o.order_date,
  o.sm_channel,
  SUM(o.order_net_revenue)    AS revenue,
  SUM(c.custom_metric)        AS custom_metric
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders`   AS o
JOIN `<your_project>.<your_dataset>.<your_table>`     AS c
  ON o.<sm_join_col> = c.<your_join_col>
WHERE o.is_order_sm_valid = TRUE
  AND DATE(o.order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY o.order_date, o.sm_channel
ORDER BY o.order_date DESC

-- Fan-out-safe join pattern (pre-aggregate first when cardinality > 1)
WITH custom_agg AS (
  SELECT <join_key>, SUM(<metric>) AS custom_metric
  FROM `<your_project>.<your_dataset>.<your_table>`
  GROUP BY <join_key>          -- collapse to 1 row per join key
)
SELECT
  o.order_date,
  SUM(o.order_net_revenue) AS revenue,
  SUM(c.custom_metric)     AS custom_metric
FROM `sm-<tenant_id>.sm_transformed_v2.obt_orders` AS o
JOIN custom_agg AS c ON o.<sm_join_col> = c.<join_key>
WHERE o.is_order_sm_valid = TRUE
GROUP BY o.order_date
ORDER BY o.order_date DESC
```

### Common join keys to SM tables

| Your data | SM join column | SM table |
|-----------|---------------|----------|
| Order-level data | `sm_order_key` | `obt_orders`, `obt_order_lines` |
| Customer-level data | `sm_customer_key` | `obt_customers` |
| Product/SKU data | `sku` or `product_variant_id` | `obt_order_lines` |
| Date-level data | `DATE(order_processed_at_local_datetime)` | `obt_orders` |

---

## Example: Inventory Table

```
## Table: inventory_snapshots

- **Project**: acme-corp-data
- **Dataset**: ops_warehouse
- **Full ref**: `acme-corp-data.ops_warehouse.inventory_snapshots`
- **Grain**: One row per (sku, snapshot_date)
- **Join key to SM data**: `sku` (SM obt_order_lines) = `sku` (this table)
- **Caveats**: Daily snapshots only — use snapshot_date = CURRENT_DATE() - 1 for latest.
  SKU column has mixed case; normalize with LOWER(sku) on both sides.
- **PII columns**: none
```

Example query mixing inventory with SM order data:

```sql
WITH latest_inventory AS (
  SELECT LOWER(sku) AS sku, units_on_hand, reorder_threshold
  FROM `acme-corp-data.ops_warehouse.inventory_snapshots`
  WHERE snapshot_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)
SELECT
  ol.product_title,
  LOWER(ol.sku)                      AS sku,
  SUM(ol.order_line_quantity)        AS units_sold_30d,
  MAX(inv.units_on_hand)             AS units_on_hand,
  MAX(inv.reorder_threshold)         AS reorder_threshold
FROM `sm-<tenant_id>.sm_transformed_v2.obt_order_lines`       AS ol
LEFT JOIN latest_inventory                                      AS inv
       ON LOWER(ol.sku) = inv.sku
WHERE ol.is_order_sm_valid = TRUE
  AND DATE(ol.order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY ol.product_title, LOWER(ol.sku)
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
- **Join key to SM data**: `customer_email` (this table) → hash-join via SHA256(LOWER(email))
- **Caveats**: customer_email is PII — use hashed join, never expose raw values.
  A customer may have multiple tickets; pre-aggregate before joining to obt_customers.
- **PII columns**: customer_email, customer_name, ticket_body
```

Example query — support volume by customer segment (PII-safe):

```sql
WITH ticket_counts AS (
  SELECT
    TO_HEX(SHA256(LOWER(customer_email))) AS email_hash,
    COUNT(*)                               AS ticket_count,
    COUNTIF(resolved = TRUE)               AS resolved_count
  FROM `acme-corp-data.helpdesk.support_tickets`
  WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
  GROUP BY email_hash   -- pre-aggregate: 1 row per customer
)
SELECT
  c.subscriber_status,
  AVG(t.ticket_count)    AS avg_tickets_per_customer,
  COUNT(c.sm_customer_key) AS customers
FROM `sm-<tenant_id>.sm_transformed_v2.obt_customers`            AS c
JOIN ticket_counts                                                AS t
  ON TO_HEX(SHA256(LOWER(c.customer_email))) = t.email_hash
GROUP BY c.subscriber_status
ORDER BY avg_tickets_per_customer DESC
```
