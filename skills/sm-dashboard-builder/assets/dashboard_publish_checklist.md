# Dashboard Publish Checklist

Use this before sharing a dashboard HTML file or BI-tool handoff.

- [ ] Dashboard answers one clear operating or business decision.
- [ ] Every tile has a metric contract or an explicit blocker note.
- [ ] Every SQL tile has a copy/paste SQL receipt.
- [ ] Every SQL query was dry-run and `dry_run_bytes` is recorded.
- [ ] Every executed query has `row_count` recorded.
- [ ] Freshness was checked from SourceMedium metadata or documented as unknown.
- [ ] Ratios/rates include numerator, denominator, and denominator safety checks.
- [ ] Date range, timezone, store scope, and attribution lens are visible.
- [ ] Partial periods are excluded or clearly labeled.
- [ ] Filters are real and wired to every affected tile, or shown as static scope.
- [ ] High-cardinality dimensions are Top-K limited or table-based.
- [ ] Non-additive metrics are recomputed at the displayed grain.
- [ ] No raw PII is embedded unless explicitly requested and justified.
- [ ] Chart fields match returned data fields.
- [ ] `validate_dashboard_manifest.py --strict` passes for manifest-based output.
- [ ] Standalone HTML is labeled as point-in-time unless refresh is implemented.
