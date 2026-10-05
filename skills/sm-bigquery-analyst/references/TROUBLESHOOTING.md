# Troubleshooting

Common failures and how to resolve them. Start with
`python scripts/sm_bq_doctor.py --project <project>`: it names the failing step.

## How Access Works

- **Every plan** reaches the data through the SourceMedium MCP, signed in with
  the user's SourceMedium account. Agency (partner) access works this way too.
- **Direct warehouse access** (querying BigQuery with the user's own Google
  account) is part of Pro, the dedicated warehouse:
  - An accepted, direct workspace member is granted it automatically, usually
    within minutes, with a full re-sync every few hours.
  - The grant goes to the Google account whose email matches the workspace
    membership. `gcloud auth list` must show that same account.
  - Viewers can read and run queries; editors and admins can also create their
    own datasets, and admins can grant the customer's own service accounts.
  - The customer's own Google Cloud admin cannot grant it to people:
    hand-added user grants of SourceMedium's managed warehouse roles are
    removed at the next sync.
- **Foundation plans have no direct warehouse access.** Use the MCP.

So the fix for missing direct access on Pro is a workspace invitation, not an
IAM ticket. Use `assets/BIGQUERY_ACCESS_REQUEST_TEMPLATE.md`.

## CLI Tool Issues

### gcloud or bq not found

```bash
gcloud --version
bq version
# Install the Google Cloud CLI: https://cloud.google.com/sdk/docs/install
```

### Wrong project

The doctor and the query scripts take `--project`, so the gcloud default does not
have to match. To change the default anyway:

```bash
gcloud config get-value project
gcloud config set project <project>
```

## Authentication Issues

### Not authenticated, or the wrong Google account

```bash
gcloud auth list
gcloud auth login
gcloud auth application-default login
```

Sign in as the Google account that matches your SourceMedium workspace email.

## Permission Issues

### Access Denied: bigquery.jobs.create

You cannot run query jobs in this project. Either the plan has no direct
warehouse access (use the MCP), your workspace membership has not synced yet
(wait a few minutes after accepting the invitation), you are signed in as a
different Google account, or your access is agency-only. If none applies,
contact SourceMedium support.

### Access Denied: bigquery.tables.getData, or "Not found: Dataset"

- Use the dataset names `get_data_context` (or the doctor) reports. On the
  shared warehouse they carry a tenant prefix: `<tenant>_sm_transformed_v2`.
- You can read only your own tenant's datasets. A dataset named after another
  tenant is not yours; never try a similar name.
- A table listed only for the dedicated warehouse (see `SCHEMA.md`) does not
  exist on the shared one.

### Table not found

1. Verify the project and the resolved dataset names (doctor output).
2. Verify the table name in `dim_data_dictionary`.
3. Check whether the table exists on this warehouse layout (`SCHEMA.md`).

## Query Errors

### Unrecognized name: smcid / channel / order_date

Those columns do not exist in customer tables. Use `sm_store_id`, `sm_channel`,
and `DATE(order_processed_at_local_datetime)`. `SCHEMA.md` lists more.

### Unrecognized name: sm_marketing_channel

Not on `obt_orders` (use `sm_channel`). It does exist on
`fct_order_attribution_signals`.

### Error comparing a TIMESTAMP to a DATE

UTC `*_at` columns are TIMESTAMPs, which BigQuery will not compare to a DATE.
Report on the store-local column instead, through `DATE()`:

```sql
WHERE DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
```

### A date range is missing most of its last day

`*_local_datetime` columns are DATETIMEs. Compared to a DATE they run without
error, but the DATE is read as midnight, so `<= DATE '2026-01-31'` drops
everything after 00:00 on the 31st. Wrap the column:
`DATE(order_processed_at_local_datetime) <= DATE '2026-01-31'`.

### Division by zero

Use `SAFE_DIVIDE(numerator, denominator)`.

### A filter matches nothing

Categorical values are normalized (lowercase, underscores) for some columns and
not others. List the real values with `SELECT DISTINCT` and match exactly.

## Result Problems

### Exit 7 / status `truncated`

The result had more rows than `--max-rows`. Aggregate further or narrow the
query; raise `--max-rows` only when the full row set is genuinely needed. Never
present a truncated result as complete.

### A number disagrees with SourceMedium's dashboards or the MCP

Check, in order: the valid-order filter, the catalog definition and its
`filter_condition`, the date column and timezone, store and channel scope, and
whether a ratio was averaged instead of aggregated then divided.

## Cost and Performance

### Over the bytes cap (exit 5)

1. Select fewer columns: BigQuery bills the columns read.
2. Narrow the date range.
3. Pre-aggregate in a CTE before joining.
4. Raise `--maximum-bytes-billed` only with the user's approval.

### Resources exceeded

Reduce the date range, group by fewer columns, or split the work into smaller
queries.

## Getting Help

1. Run the doctor and keep its output.
2. Copy the exact error message.
3. If the SourceMedium MCP is connected, `get_account_health` reports connection
   and pipeline problems.
4. Share both with SourceMedium support.
