# Integrating with SourceMedium Data

Bespoke pipelines live next to SourceMedium-managed data, not inside it.
This file is the boundary contract: what you may read, what you must not
write, and which join keys and flags keep your tables consistent with ours.

## 1. The boundary

- **Read** from SourceMedium datasets. **Write** only to your own. Never
  create, modify, or delete tables in a SourceMedium dataset; they are built
  and published by SourceMedium jobs, and your writes will be overwritten or
  break their contracts.
- Bespoke pipelines need direct warehouse access, which is part of
  SourceMedium Pro, the dedicated warehouse:
  - SourceMedium's datasets are `sm_transformed_v2`, `sm_metadata`,
    `sm_views`, `sm_experimental`, `sm_utils`, and `sm_sources`, in the
    tenant's own project.
  - Your tables go in new datasets in that project (SourceMedium workspace
    editors and admins can create them), or in another project you own in the
    same region (US).
  - Foundation plans live in SourceMedium's shared project
    (`sourcemedium-bi`, `<tenant>_sm_*` datasets), where customers cannot
    create anything and have no direct access, so there is no pipeline to
    build there.

- Resolve dataset names from the live warehouse per project, never from
  memory: the `sm-bigquery-analyst` doctor script or the SourceMedium MCP's
  `get_data_context` prints them. Pass them to the pipeline as parameters.
- Before the first write, list what already exists with
  `INFORMATION_SCHEMA.SCHEMATA` and `INFORMATION_SCHEMA.TABLES` and confirm the
  destination is yours. On a dedicated warehouse,
  `<sm_metadata>.dim_tenant_custom_objects` adds which objects were used in the
  last 180 days and whether each is `sm_owned` or `tenant_owned`; it is a usage
  inventory, so an unused dataset will not appear in it.
- Name your datasets so no one has to guess which is which (`loyalty_raw`,
  not `sm_loyalty`). Never start a dataset name with `sm_`, `smdelivery_`, or
  `_`: SourceMedium treats those as its own, and the SourceMedium MCP will not
  expose them to the customer's AI tools. Customer datasets with ordinary names
  on a dedicated warehouse are reachable through the MCP's `run_bigquery_sql`.
- If the `sm-bigquery-analyst` skill is installed, use it for warehouse
  discovery and access verification.

## 2. Join keys and validity

- Join orders on the source platform's ids: `sm_store_id`, `source_system`,
  and `order_id` (`order_name` and `order_number` sit alongside it on
  `obt_orders`). `order_id` is unique only within a store and source system,
  so a join on `order_id` alone can match another platform's order.
- **`sm_order_key` is SourceMedium's own surrogate**: a hash of those three
  columns. It is the table's primary key and what you group by inside the
  warehouse, but your source system never saw it, so it is not the join key
  from outside. Use it only for tables derived from SourceMedium's.
- Customers: `sm_store_id`, `source_system`, `customer_id`. Guest checkouts
  have no `customer_id`. For email matching, `obt_customers.customer_email_hashed`
  is `TO_BASE64(SHA256(LOWER(TRIM(email))))`: base64, not hex.
- Confirm exact column names with `INFORMATION_SCHEMA.COLUMNS` before
  encoding any of them.
- Confirm the key's cardinality on your side first: joining a fan-out table
  to order revenue silently multiplies it. Pre-aggregate your side unless the
  join key is provably 1:1.
- For order analyses, filter `is_order_sm_valid = TRUE`; without it your
  totals will not reconcile to any SourceMedium surface. It also drops fully
  refunded orders and every channel other than `online_dtc`, `amazon`,
  `tiktok_shop`, `retail`, and `wholesale`, which matters when your side
  carries those orders.
- Use `order_net_revenue` for revenue unless the metric contract says
  otherwise, and prefer `*_local_datetime` columns for date logic so your
  day boundaries match SourceMedium reporting.

## 3. Metrics stay canonical

- SourceMedium metrics are the source of truth unless the pipeline spec
  explicitly defines a custom metric from customer-owned data, and then the
  custom metric gets a different name, never a shadowed one.
- Resolve metric names through `dim_semantic_metric_catalog` rather than
  guessing columns. Its `calculation` column is documentation, not runnable
  SQL: apply the metric's `filter_condition` (its column names can be internal
  ones, such as `valid_order_sequence` for the published
  `sm_valid_order_sequence`; check them against the table), rebuild ratios from
  `dependent_metrics`, and aggregate each side before dividing. If the
  `sm-dashboard-builder` skill is installed, the file at
  `sm-dashboard-builder/assets/metric_contract_template.json` (in that skill's
  directory, not this one) is the right shape for writing down name, formula,
  source table, grain, filters, and timezone.
- Enumerated values (channel, platform, status) are discovered with
  `SELECT DISTINCT` first, then matched exactly. Never encode a guessed
  category string into a join or filter.

## 4. Freshness expectations

- SourceMedium tables refresh on SourceMedium's schedule, not yours. Gate on
  evidence, never on the clock:
  - `<sm_metadata>.obt_data_movement_job_logs_v1` records each publish attempt
    per table (`requested_model_name`, `status`, `dry_run`, `rows_written`,
    `created_at`). For each SourceMedium table you depend on, require its
    latest row with `status = 'success'` and `dry_run = FALSE` to fall inside
    your expected window. There is no single "publish complete" row, and a
    no-op refresh is still logged as a success.
  - `table_last_data_date` in `dim_data_dictionary` says how recent the data
    itself is.
- If your pipeline must run before SourceMedium's daily publish, build
  against yesterday's closed data explicitly and say so. Depending on
  same-day SourceMedium partitions is depending on a schedule you don't own.
- Your pipeline's own freshness checks (per `references/DATA_QUALITY.md`)
  cover your tables; SourceMedium freshness is an input fact, not your
  failure. When a join produces short totals, check SourceMedium's freshness
  before debugging your extract.
