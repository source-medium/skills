# Charting

Pick chart forms from the data contract first, then choose the renderer that
fits the user's target. Vega-Lite is only the bundled standalone HTML default,
not a hard requirement.

## Chart Selection

| Analytical intent | Preferred chart |
|-------------------|-----------------|
| KPI / latest value | Scorecard |
| Trend over time | Line |
| Ranked magnitude | Horizontal bar |
| Share / mix over time | Stacked or normalized stacked bar |
| Cohort LTV / retention | Heatmap or cohort curves |
| Funnel | Ordered horizontal stage bars |
| Distribution | Histogram or box plot |
| Relationship | Scatter / bubble |
| Exact row-level comparison | Table |
| Blocked or unavailable metric | Note with blocker and next step |

Zero charts is valid when a chart would add no information.

## Renderer Selection

- Use the existing app or BI tool's charting stack when the dashboard is being
  added to an existing codebase or workspace.
- Use Metabase, Looker Studio, Tableau, or Power BI native visualization
  settings when the target is one of those tools.
- Use the bundled Vega-Lite HTML builder for portable standalone artifacts,
  quick local drafts, and agent-to-agent handoff.
- Use ECharts, Recharts, Observable Plot, Chart.js, or another library when the
  user asks for it or the surrounding project already standardizes on it.
- Keep the SQL/result contract independent from renderer-specific chart config
  so the dashboard can be ported across tools.

## Portable HTML Builder Rules

These rules apply when using `scripts/build_dashboard_html.py`, which renders
Vega-Lite v6 specs.

- Use explicit field types (`quantitative`, `temporal`, `nominal`, `ordinal`) so
  axes and legends render correctly without guessing.
- Non-additive metrics (AOV, ROAS, MER, CAC, rates) must not be summed across
  rows in chart data — recompute them at the displayed grain.
- For legacy embeds requiring v5, downgrade deliberately and note the constraint
  in the dashboard notes.

## SourceMedium Visualization Semantics

- Derived-metric questions must chart the derived metric first. Counts and
  denominators belong in tooltips or secondary charts.
- Period-over-period dashboards often need two views: magnitude and change.
- Unequal period lengths require day-normalized metrics before comparison.
- Non-additive metrics such as AOV, ROAS, MER, CAC, rates, and percentages
  should not be summed in charts.
- Use automatic or range-aware time grain when the target BI tool supports it;
  otherwise choose a grain that fits the dashboard time range and document it.
- For Top-K categories, group or omit the long tail explicitly.
- For LTV/cohort views, include cohort size context and avoid declaring tiny
  cohorts as winners.

## HTML Dashboard Chart QA

Before finalizing:

- Every chart has a source SQL receipt.
- Every chart has enough rows to support its claim.
- Units match axis labels and tooltip formats.
- Partial periods are labeled or excluded.
- Legends are visible for color encodings.
- High-cardinality dimensions are Top-K limited.
- Empty or all-null metrics are not charted.
- Notes/blockers replace charts when the verified data cannot support the requested metric.
