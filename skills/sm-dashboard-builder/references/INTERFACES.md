# Interfaces

HTML is the default output. Use other interfaces when the user asks or when the
dashboard must be refreshable inside an existing BI tool.

## HTML Default

Use a manifest-driven standalone HTML dashboard:

- Embed query results as JSON.
- Embed chart specs/config next to the data. The bundled HTML builder expects
  Vega-Lite specs, but custom HTML may use another chart library.
- Include SQL receipts and data freshness.
- Use the smallest renderer that fits the target. For the bundled builder this
  means CDN scripts for `vega`, `vega-lite`, and `vega-embed` unless offline
  output is requested.
- Do not add fake filters. If controls are not wired to data, present scope as
  static context.
- Treat standalone HTML as a point-in-time artifact unless a real refresh path
  is implemented.

Best for:

- Fast operator dashboard drafts
- Shareable analysis artifacts
- Local development in Claude Code/Codex
- Auditable dashboards where SQL is visible

Not best for:

- Large raw datasets that require browser-side aggregation
- Dashboards that need governed, scheduled refresh
- Dashboards where row-level permissions must be enforced in the BI layer

## Metabase

Metabase handoff should include:

- One SQL question/card per tile.
- Field names, metric definitions, and expected visualization type.
- Dashboard layout order and filter mapping.
- Required dashboard filters: date range, store, channel/source system when relevant.
- Notes on whether queries are native SQL or should become modeled questions.
- Default time range, refresh expectations, and whether the dashboard should be
  parameterized with field filters or native SQL variables.

Use `assets/metabase_cards_template.json` as the handoff shape when no Metabase
API/tool is available.

Do not promise Metabase creation unless the agent has a Metabase API/tool
available and authenticated. Otherwise produce a build checklist and SQL cards.

## Looker Studio / Tableau / Power BI

Provide BI-ready data-source SQL or views:

- Stable column names and types.
- One row per intended visualization grain.
- Date field and dimensions clearly named.
- Numeric fields already normalized when needed.
- Metric definitions documented next to field names.

For Looker Studio specifically, keep data-source tables narrow and dashboard
friendly. Avoid requiring complex calculated fields in the UI when BigQuery SQL
can compute them accurately.

## Embedded App / React

If building an app instead of standalone HTML:

- Keep SQL/result contracts separate from presentation components.
- Use a chart library intentionally: the project's existing library first, or
  Vega-Lite, ECharts, Recharts, Observable Plot, Chart.js, or similar when
  starting from scratch.
- Preserve SQL receipts and metric definitions in a developer/debug panel or
  downloadable artifact.
- Validate rendered charts in a browser; nonblank canvas/SVG and readable text
  are required.
