# Changelog

## Unreleased

- Expanded `sm-bigquery-analyst` with stronger SourceMedium metadata discovery,
  custom dataset support, semantic metric guidance, QA tooling, eval metadata,
  and OpenAI/Codex skill metadata.
- Added `sm-dashboard-builder` for correctness-first BI dashboard creation from
  SourceMedium BigQuery data and operator-owned warehouse tables.
- Added dashboard manifest validation, strict publish checks, HTML rendering,
  metric contract templates, Metabase handoff templates, and example dashboard
  manifests.
- Added package-level install, update, and QA guidance.
- Added `sm-pipeline-builder` for spec-first bespoke data pipelines that land
  in customer-owned BigQuery datasets alongside SourceMedium data, or publish
  customer-owned tables out of BigQuery into a system the operator owns.
  Ships incremental-load, BigQuery, data-quality, operations, and integration
  references plus a readiness checklist. The spec validator enforces the hard
  rules a spec can break on paper: writes into `sm_*` datasets, credential
  values carried instead of secret names, primary keys not derivable from the
  declared grain, and `append_restate` streams with no window column to make
  the fetch and delete windows identical. Malformed specs exit 2 with a
  message rather than a traceback.
