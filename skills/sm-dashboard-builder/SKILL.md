---
name: sm-dashboard-builder
description: >
  Use this skill when an operator wants to build a correct, accurate, and useful
  dashboard from SourceMedium BigQuery data or from their own warehouse tables
  joined to SourceMedium data. Default to a standalone HTML dashboard with
  auditable SQL receipts and portable chart specs. Also use for dashboard SQL
  planning, BI metric validation, chart selection, Metabase/Looker/Tableau-ready
  query handoff, or dashboard QA. Do not use for mutating warehouse data.
metadata:
  author: sourcemedium
  version: "1.0"
  short-description: "Build SourceMedium BI dashboards from BigQuery."
  requirements: "Requires access to SourceMedium BigQuery data; bundled HTML builder uses Vega-Lite/Vega-Embed CDNs by default, but other chart libraries are valid when requested or already established."
---

# SourceMedium Dashboard Builder

Build BI dashboards from SourceMedium warehouse data with correctness first:
discover the data, define metric contracts, dry-run and execute safe SQL, then
render a clear dashboard. HTML is the default output because it is portable
across Claude Code, Codex, OpenClaw-style agents, and ordinary browsers.

## Workflow

1. **Clarify the dashboard job**: audience, business decision, timeframe,
   store/channel scope, refresh expectations, and target interface.
   - Every tile must answer a decision-making question or provide evidence.
   - If a requested metric cannot be computed correctly, create a note/blocker
     instead of substituting a different metric.
2. **Discover data before designing**:
   - SourceMedium metadata: `sm_metadata.dim_data_dictionary`
   - Metric catalog: `sm_metadata.dim_semantic_metric_catalog`
   - Actual store IDs, categorical values, freshness, and schema
   - Customer-owned tables only after documenting grain, join keys, PII, and coverage
3. **Define metric contracts** before SQL:
   - Metric name, formula, source table, grain, filters, numerator/denominator
   - Timezone/date field, scope, attribution lens, and non-additive warnings
   - Use `assets/metric_contract_template.json` for structured definitions
4. **Write BI-safe SQL**:
   - SELECT/WITH only
   - Fully qualified BigQuery tables
   - Bounded time filters and dry-run bytes
   - One query per dashboard tile when possible
   - Explicit SQL receipt for every tile
5. **Validate results before visualizing**:
   - Freshness, row count, nulls, distinct values, denominator safety, and join cardinality
   - Metric totals reconcile to the intended source
6. **Design the dashboard**:
   - Scorecards first, trends second, breakdowns/drilldowns third, diagnostics/evidence last
   - Choose charts that add information beyond the title/summary
   - Use the target interface's existing chart library when known; otherwise the bundled HTML builder uses Vega-Lite as a portable default
   - Add filters only when they are wired to every affected tile
   - Pre-aggregate before embedding data in standalone HTML; do not ship large raw datasets to the browser
7. **Build and QA**:
   - Validate drafts with `scripts/validate_dashboard_manifest.py`
   - Use `--strict` before sharing or BI-tool handoff
   - Build standalone HTML with `scripts/build_dashboard_html.py`
   - Run package QA with `scripts/qa_sm_dashboard_skill.py`

## Output Defaults

Default deliverable:

- `dashboard.html` — standalone HTML with embedded data/specs; the bundled builder uses Vega-Lite, but custom HTML/app output may use another chart library
- `dashboard_manifest.json` — source manifest for rebuilding
- `sql/` or a SQL receipt section — one copy/paste BigQuery query per tile
- `README` or notes section — metric definitions, caveats, data freshness, and QA status

If the user asks for another interface:

- **Metabase**: provide SQL cards/questions plus dashboard layout instructions.
- **Looker Studio/Tableau/Power BI**: provide BI-ready SQL/data-source queries and field definitions.
- **Embedded app**: provide component-ready JSON specs and data contracts.

## Reference Routing

Read only what you need:

- `references/DASHBOARD_SQL.md` — BI-safe SourceMedium SQL and metric contracts.
- `references/DASHBOARD_DESIGN.md` — layout, dashboard information architecture, and UX rules.
- `references/CHARTING.md` — chart selection, renderer selection, and visualization QA.
- `references/INTERFACES.md` — HTML default, Metabase, Looker Studio, Tableau, Power BI, and app handoff.
- `assets/dashboard_manifest_template.json` — manifest shape consumed by the HTML builder script.
- `assets/metric_contract_template.json` — structured metric definition template.
- `assets/metabase_cards_template.json` — Metabase SQL card handoff shape.
- `assets/examples/executive_overview_manifest.json` — small example manifest.
- `assets/dashboard_publish_checklist.md` — final share/handoff checklist.

If the task also needs raw warehouse setup/access debugging, use the
`sm-bigquery-analyst` skill if installed.

## Hard Rules

- Never fabricate data. If a query cannot run, show the exact failure and stop that tile.
- Do not build charts from guessed table names, guessed columns, or guessed categorical values.
- Do not mutate warehouse data. No DDL, DML, exports, or permission changes.
- Do not mix tenants or stores unless the user explicitly asks and the scope is verified.
- Do not present ratios without denominator checks.
- Do not chart partial periods as if complete.
- Do not use raw PII in dashboard output unless explicitly requested and justified.
- Prefer `order_net_revenue`, `is_order_sm_valid = TRUE`, and local datetime fields for order reporting unless the metric contract says otherwise.

## Build Command

Run from the skill directory (`skills/sm-dashboard-builder/`):

```bash
python scripts/validate_dashboard_manifest.py assets/dashboard_manifest_template.json --strict
python scripts/build_dashboard_html.py assets/dashboard_manifest_template.json --out dashboard.html
```

For package QA:

```bash
python scripts/qa_sm_dashboard_skill.py
```
