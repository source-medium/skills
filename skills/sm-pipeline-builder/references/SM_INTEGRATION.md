# Integrating with SourceMedium Data

Bespoke pipelines live next to SourceMedium-managed data, not inside it.
This file is the boundary contract: what you may read, what you must not
write, and which join keys and flags keep your tables consistent with ours.

## 1. The boundary

- **Read** from SourceMedium datasets. **Write** only to your own.
  Never create, modify, or delete tables in `sm_metadata`,
  `sm_transformed_v2`, `sm_experimental`, or any `sm_*` dataset — those are
  built and published by SourceMedium jobs, and your writes will be
  overwritten or break their contracts.
- If the `sm-bigquery-analyst` skill is installed, use it for warehouse
  discovery and access verification. Otherwise discover datasets the same
  way: `INFORMATION_SCHEMA.SCHEMATA`, then
  `sm_metadata.dim_data_dictionary` for table freshness and
  `sm_metadata.dim_semantic_metric_catalog` for metric definitions.
- Dataset names vary by layout: most tenants get a dedicated `sm-<tenant>`
  project with plain `sm_metadata` / `sm_transformed_v2` datasets, but some
  hosted layouts use tenant-prefixed dataset names instead. Resolve them from
  the live warehouse per project — never hardcode a layout. Pass dataset
  names as pipeline parameters.
- The boundary is the **dataset**, not the project. Your bespoke datasets may
  legitimately live in the same `sm-<tenant>` project as the SourceMedium
  ones; what you must never do is write into a dataset SourceMedium
  publishes. Name your datasets so no one has to guess which is which
  (`loyalty_raw`, not `sm_loyalty`), and confirm the resolved destination
  project and dataset before the first write.

## 2. Join keys and validity

- Join to SourceMedium orders on your entity's store/account id to
  `sm_store_id`, plus the source-platform order identifier. In
  `sm_transformed_v2.obt_orders` that is `order_id` (with `order_name` and
  `order_number` alongside it) — the id your upstream system also knows.
  **`sm_order_key` is SourceMedium's own surrogate**: it is the table's
  primary key and it is what you group by inside the warehouse, but it does
  not exist in your source system, so it is never the join key from outside.
  Confirm which identifier your side actually carries, and confirm the exact
  column names with `INFORMATION_SCHEMA.COLUMNS` before encoding either.
- Scope the join by `sm_store_id`. A multi-store project keeps every store in
  the same table, and a source-platform order id is unique per store, not
  necessarily across them.
- Confirm the key's cardinality on your side first: joining a fan-out table
  to order revenue silently multiplies it. Pre-aggregate your side unless the
  join key is provably 1:1.
- For order analyses, filter `is_order_sm_valid = TRUE`. That flag excludes
  test, cancelled, and otherwise invalid orders — without it your totals
  will not reconcile to any SourceMedium surface.
- Use `order_net_revenue` for revenue unless the metric contract says
  otherwise, and prefer `*_local_datetime` columns for date logic so your
  day boundaries match SourceMedium reporting.
- Use `sm_store_id`, not any similarly-named id from adjacent systems.
  Confirm the exact column with `INFORMATION_SCHEMA.COLUMNS` before encoding
  it as a join constant.

## 3. Metrics stay canonical

- SourceMedium metrics are the source of truth unless the pipeline spec
  explicitly defines a custom metric from customer-owned data — and then
  the custom metric gets a different name, never a shadowed one.
- Resolve metric names through `dim_semantic_metric_catalog` (labels,
  aliases, calculations) rather than guessing columns. If the
  `sm-dashboard-builder` skill is installed, the file at
  `sm-dashboard-builder/assets/metric_contract_template.json` (in that
  skill's directory, not this one) is the right shape for writing down name,
  formula, source table, grain, filters, and timezone.
- Enumerated values (channel, platform, status) are discovered with
  `SELECT DISTINCT` first, then matched exactly. Never encode a guessed
  category string into a join or filter.

## 4. Freshness expectations

- SourceMedium tables refresh on SourceMedium's schedule, not yours.
  Read `table_last_data_date` in `dim_data_dictionary` and gate your
  pipeline's dependent reads on it — don't assume today's partition exists
  because your extract finished.
- If your pipeline must run before SourceMedium's daily publish, build
  against yesterday's closed data explicitly and say so. Depending on
  same-day SourceMedium partitions is depending on a schedule you don't own.
- Your pipeline's own freshness checks (per `references/DATA_QUALITY.md`)
  cover your tables; SourceMedium freshness is an input fact, not your
  failure. When a join produces short totals, check their freshness date
  before debugging your extract.
