#!/usr/bin/env python3
"""Build a portable HTML dashboard from a SourceMedium dashboard manifest."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from dashboard_manifest import load_manifest, safe_id, validate_manifest_or_raise


def escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def format_json_for_script(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (
        raw.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_kpis(kpis: list[Any]) -> str:
    if not kpis:
        return ""
    cards: list[str] = []
    for raw in kpis:
        if not isinstance(raw, dict):
            continue
        delta = raw.get("delta")
        delta_html = f'<span class="kpi-delta">{escape(delta)}</span>' if delta not in (None, "") else ""
        note = raw.get("note")
        note_html = f'<p class="kpi-note">{escape(note)}</p>' if note else ""
        cards.append(
            f"""
            <article class="kpi-card">
              <div class="kpi-label">{escape(raw.get("label", "Metric"))}</div>
              <div class="kpi-value">{escape(raw.get("value", ""))}</div>
              {delta_html}
              {note_html}
            </article>
            """
        )
    return f'<section class="kpi-grid" aria-label="Key metrics">{"".join(cards)}</section>'


def render_tables(tables: list[Any]) -> str:
    sections: list[str] = []
    for raw_table in tables:
        if not isinstance(raw_table, dict):
            continue
        rows = raw_table.get("rows", [])
        if not rows:
            continue
        headers: list[str] = []
        for row in rows:
            if isinstance(row, dict):
                for key in row:
                    if key not in headers:
                        headers.append(key)
        if not headers:
            continue
        body_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            body_rows.append(
                "<tr>"
                + "".join(f"<td>{escape(row.get(header, ''))}</td>" for header in headers)
                + "</tr>"
            )
        sections.append(
            f"""
            <section class="table-panel">
              <h2>{escape(raw_table.get("title", raw_table.get("id", "Table")))}</h2>
              <div class="table-scroll">
                <table>
                  <thead><tr>{"".join(f"<th>{escape(header)}</th>" for header in headers)}</tr></thead>
                  <tbody>{"".join(body_rows)}</tbody>
                </table>
              </div>
            </section>
            """
        )
    return "".join(sections)


def render_dashboard(manifest: dict[str, Any], warnings: list[str]) -> str:
    charts = []
    for chart in manifest.get("charts", []):
        dom_id = f"chart-{safe_id(chart['id'])}"
        charts.append(
            f"""
            <section class="chart-panel">
              <div class="panel-heading">
                <h2>{escape(chart.get("title", chart["id"]))}</h2>
                <p>{escape(chart.get("subtitle", ""))}</p>
              </div>
              <div id="{dom_id}" class="chart" aria-label="{escape(chart.get("title", chart["id"]))}"></div>
            </section>
            """
        )

    receipts = []
    for chart in manifest.get("charts", []):
        receipts.append(
            f"""
            <details>
              <summary>{escape(chart.get("title", chart["id"]))}</summary>
              <pre><code>{escape(chart["sql"])}</code></pre>
            </details>
            """
        )
    for table in manifest.get("tables", []):
        receipts.append(
            f"""
            <details>
              <summary>{escape(table.get("title", table["id"]))}</summary>
              <pre><code>{escape(table["sql"])}</code></pre>
            </details>
            """
        )

    notes = manifest.get("notes", [])
    note_items = "".join(f"<li>{escape(note)}</li>" for note in notes if isinstance(note, str))
    warning_items = "".join(f"<li>{escape(warning)}</li>" for warning in warnings)
    dashboard_json = format_json_for_script(manifest)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(manifest["title"])}</title>
  <script src="https://cdn.jsdelivr.net/npm/vega@6"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@6"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@7"></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #18202b;
      --muted: #5b6778;
      --line: #d9dee7;
      --accent: #1868db;
      --accent-2: #0f766e;
      --warn: #8a5a00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      letter-spacing: 0;
    }}
    header, main, footer {{
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
    }}
    header {{
      padding: 28px 0 18px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: clamp(28px, 4vw, 44px);
      line-height: 1.05;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0;
      font-size: 18px;
      line-height: 1.25;
      letter-spacing: 0;
    }}
    p {{ color: var(--muted); line-height: 1.5; }}
    .scope {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }}
    .pill {{
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    main {{ padding: 22px 0 40px; }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .kpi-card, .chart-panel, .table-panel, .notes, .receipts {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(24, 32, 43, 0.04);
    }}
    .kpi-card {{ padding: 16px; min-height: 116px; }}
    .kpi-label {{ color: var(--muted); font-size: 13px; font-weight: 650; }}
    .kpi-value {{ margin-top: 8px; font-size: 28px; font-weight: 750; }}
    .kpi-delta {{ color: var(--accent-2); font-weight: 700; font-size: 13px; }}
    .kpi-note {{ margin: 8px 0 0; font-size: 13px; }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr));
      gap: 14px;
      align-items: start;
    }}
    .chart-panel {{ padding: 16px; min-width: 0; }}
    .panel-heading {{ margin-bottom: 10px; }}
    .panel-heading p {{ margin: 4px 0 0; font-size: 13px; }}
    .chart {{ width: 100%; min-height: 320px; }}
    .table-panel {{ margin-top: 14px; padding: 16px; }}
    .table-scroll {{ overflow-x: auto; margin-top: 12px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px; text-align: left; white-space: nowrap; }}
    th {{ color: var(--muted); font-weight: 700; }}
    .notes, .receipts {{ margin-top: 14px; padding: 16px; }}
    .notes ul {{ margin: 8px 0 0; padding-left: 20px; color: var(--muted); }}
    details {{ border-top: 1px solid var(--line); padding: 10px 0; }}
    details:first-of-type {{ border-top: 0; }}
    summary {{ cursor: pointer; font-weight: 700; }}
    pre {{
      overflow-x: auto;
      padding: 12px;
      border-radius: 6px;
      background: #f3f5f8;
      color: #172033;
      line-height: 1.45;
    }}
    .warnings {{ color: var(--warn); }}
    footer {{ padding: 0 0 28px; color: var(--muted); font-size: 12px; }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(manifest["title"])}</h1>
    <p>{escape(manifest.get("subtitle", ""))}</p>
    <div class="scope">
      <span class="pill">Project: {escape(manifest.get("scope", {}).get("project", "not specified"))}</span>
      <span class="pill">Store: {escape(manifest.get("scope", {}).get("store", "not specified"))}</span>
      <span class="pill">Timeframe: {escape(manifest.get("scope", {}).get("timeframe", "not specified"))}</span>
      <span class="pill">Freshness: {escape(manifest.get("freshness", "not specified"))}</span>
    </div>
  </header>
  <main>
    {render_kpis(manifest.get("kpis", []))}
    <section class="chart-grid" aria-label="Dashboard charts">
      {"".join(charts)}
    </section>
    {render_tables(manifest.get("tables", []))}
    <section class="notes">
      <h2>Notes and QA</h2>
      <ul>
        {note_items}
        {warning_items}
      </ul>
    </section>
    <section class="receipts">
      <h2>SQL Receipts</h2>
      {"".join(receipts)}
    </section>
  </main>
  <footer>Generated from a SourceMedium dashboard manifest. Validate SQL, freshness, and row counts before sharing.</footer>
  <script>
    const dashboardManifest = {dashboard_json};
    for (const chart of dashboardManifest.charts || []) {{
      const domId = "chart-" + String(chart.id).trim().toLowerCase().replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
      const spec = JSON.parse(JSON.stringify(chart.vega_lite || {{}}));
      spec.data = {{ values: chart.data || [] }};
      if (!spec.autosize) {{
        spec.autosize = {{ type: "fit", contains: "padding" }};
      }}
      vegaEmbed("#" + domId, spec, {{ actions: false, renderer: "canvas" }}).catch((error) => {{
        const target = document.getElementById(domId);
        if (target) {{
          target.textContent = "Chart render failed: " + error.message;
        }}
      }});
    }}
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to dashboard manifest JSON")
    parser.add_argument("--out", type=Path, default=Path("dashboard.html"), help="Output HTML path")
    parser.add_argument("--strict", action="store_true", help="Require publish-ready metric/query QA metadata")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    warnings = validate_manifest_or_raise(manifest, strict=args.strict)
    output = render_dashboard(manifest, warnings)
    args.out.write_text(output, encoding="utf-8")
    print(f"Wrote {args.out}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
