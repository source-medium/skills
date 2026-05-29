# Dashboard Design

Use this when deciding dashboard structure, layout, and interaction patterns.

## Dashboard Information Architecture

A good BI dashboard answers one operating question. Structure it in this order:

1. **Header**: title, scope, timeframe, freshness, and filters.
2. **Scorecards**: 4-8 primary KPIs with definitions and comparison period.
3. **Primary trend**: the main time-series needed to understand movement.
4. **Breakdowns/drilldowns**: ranked dimensions such as channel, product, campaign, store, or source.
5. **Diagnostics/evidence**: freshness, attribution coverage, missing keys, row counts, caveats, and detail tables.
6. **SQL receipts**: collapsible, copy/paste queries for each tile.

## Design Principles

- Dense, calm, operational UI. Avoid marketing-page layouts.
- Decisions first: every panel answers a question that can lead to an action.
- Overview to drilldown to evidence: start with the state, then explain where to look, then expose row/detail evidence.
- Use one dashboard page for one decision; split unrelated decisions into tabs or separate pages.
- Put filters where users expect them: timeframe, store, channel, source system, customer segment.
- Make definitions discoverable near the metric, not hidden in prose.
- Use compact cards with consistent units, decimal precision, and comparison labels.
- Do not make a chart if a number or table is clearer.
- Show the freshness date and metric scope; operators need to trust the data before acting.
- Compute exactly what was asked or defer. If a metric cannot be computed from
  verified data, replace that tile with a note documenting the blocker.

## Layout Defaults for HTML

- Max page width: 1280-1440px.
- Header row: title, subtitle/scope, freshness.
- Filter/context row: pills or compact text, no fake interactive controls unless wired.
- KPI grid: responsive cards.
- Chart grid: one primary full-width chart, then two-column secondary charts.
- Tables: use sortable-looking but static tables unless actual sorting is implemented.
- SQL receipts: `<details>` blocks under each tile or a final receipts section.

## Interaction Defaults

- Filters should be global only when every relevant tile uses them.
- Common filters: date range, store, channel/source, customer segment, product/category.
- Do not display a filter control unless it is wired to charts, KPIs, tables, and receipts/notes that depend on it.
- Default time range and refresh cadence should match the audience:
  - Executive snapshot: last 30/90 days; manual refresh or daily export.
  - Marketing operations: last 7/30 days; daily or intra-day refresh when data supports it.
  - Real-time operations: shorter range and faster refresh only if query cost and freshness allow it.
- For self-contained HTML snapshots, label the dashboard as point-in-time unless it has a real refresh path.

## Performance Budgets

- Pre-aggregate data in BigQuery before embedding it in HTML.
- Keep chart series low-cardinality; use Top-K plus "Other" for long tails.
- Limit line charts to the minimum grain needed for the decision; avoid rendering thousands of points.
- Limit embedded detail tables to the rows operators need for action. Use BI tools or pagination for large tables.
- Avoid client-side aggregation over raw order/customer-level exports unless the dataset is intentionally tiny and non-sensitive.

## Dashboard Anti-Patterns

- Charting raw totals for unequal period comparisons when normalized metrics exist.
- Showing percent changes without base values.
- Ranking rates from tiny denominators without cohort-size context.
- Mixing revenue, count, and percentage in one axis.
- Hiding filters, definitions, or freshness.
- Using pie charts for more than five categories or for precise comparison.
- Treating sampled rows as full result data.
- Including panels because a metric exists, not because it answers a decision.
- Shipping filters that only update some tiles.
- Embedding large raw datasets in browser HTML.

