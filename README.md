# SourceMedium Agent Skills

Installable skills for coding agents that work with SourceMedium BigQuery data.

`sm` is the SourceMedium shorthand. Skills use `sm-<job>` names so Claude Code,
Codex, OpenClaw-style agents, and other skill clients can route to them
predictably while display metadata spells out the SourceMedium brand.

## Plans, the SourceMedium MCP, and Direct Warehouse Access

There are two ways into SourceMedium data:

- **Through SourceMedium, on every plan**: the SourceMedium MCP server
  ([docs](https://docs.sourcemedium.com/ai-analyst/connect-an-ai-assistant)),
  signed in with your SourceMedium account. It compiles SourceMedium's metric
  definitions (`query_metrics`), runs governed SQL over your SourceMedium
  datasets, and reports connection health.
- **Direct warehouse access, on Pro**: your own Google account (or your service
  accounts) querying BigQuery on your dedicated warehouse with `gcloud`/`bq`.

What each skill needs:

| Skill | Every plan (through the MCP) | Needs direct warehouse access (Pro) |
|-------|------------------------------|-------------------------------------|
| `sm-bigquery-analyst` | Questions, metrics, SQL receipts | The `bq` scripts, joins to your own tables in the warehouse, `sm_sources`, results beyond the MCP's limits |
| `sm-dashboard-builder` | HTML dashboards built from MCP results | Handoffs to BI tools that connect to BigQuery (Metabase, Looker Studio data sources, Tableau, Power BI) |
| `sm-pipeline-builder` | (none) | The whole skill |

## Quick Start (Copy/Paste)

Copy this prompt and give it to your coding agent:

```
Install and use the SourceMedium BigQuery Analyst skill.

Context:
- SourceMedium hosts analytics-ready ecommerce data in BigQuery.
- Use my SourceMedium MCP connection for SourceMedium data.
- If I have direct warehouse access (Pro), my project is: [YOUR_PROJECT]
- I may also have my own BigQuery tables that I want to join to SourceMedium data.

Tasks:
1. Install: npx skills add source-medium/skills --skill sm-bigquery-analyst
2. Confirm the MCP connection (get_data_context), or with direct access run the
   skill's setup check, and use the dataset names it reports.
3. Discover available SourceMedium tables, freshness, stores, and relevant metrics.
4. Answer my question with a SQL receipt, dry-run bytes, assumptions, and caveats.

My first question is: [ASK YOUR QUESTION]
```

## Install With `skills`

```bash
npx skills add source-medium/skills --skill sm-bigquery-analyst
npx skills add source-medium/skills --skill sm-dashboard-builder
npx skills add source-medium/skills --skill sm-pipeline-builder
```

Repo-local commands below assume you are in this repository root.

## Update Installed Skills

If you installed with the `skills` CLI, update to the latest published version
with:

```bash
npx skills update sm-bigquery-analyst -y
npx skills update sm-dashboard-builder -y
npx skills update sm-pipeline-builder -y
```

To update project-scoped or global skills explicitly:

```bash
npx skills update sm-dashboard-builder --project -y
npx skills update sm-dashboard-builder --global -y
```

If your agent installed by copying folders instead of using the CLI, replace the
copied skill directory with the latest `skills/<skill-name>/` directory from
this repository, then rerun the QA command for that skill.

See [COMPATIBILITY.md](COMPATIBILITY.md) for copy-based installs and
agent-specific notes, and [CHANGELOG.md](CHANGELOG.md) for update contents.

## Generic Install

For agents that support the Agent Skills open format, copy
`skills/<skill-name>/` into the agent's configured skills directory. Examples:

```bash
# Claude Code project skill
mkdir -p .claude/skills
cp -R skills/sm-bigquery-analyst .claude/skills/
cp -R skills/sm-dashboard-builder .claude/skills/
cp -R skills/sm-pipeline-builder .claude/skills/

# Personal skill
mkdir -p ~/.claude/skills
cp -R skills/sm-bigquery-analyst ~/.claude/skills/
cp -R skills/sm-dashboard-builder ~/.claude/skills/
cp -R skills/sm-pipeline-builder ~/.claude/skills/
```

Codex/OpenAI-compatible clients can also read the packaged `agents/openai.yaml`
metadata when their skill registry supports it.

## Available Skills

| Skill | Description |
|-------|-------------|
| `sm-bigquery-analyst` | Query SourceMedium BigQuery safely, discover warehouse metadata, and join operator-owned tables with SourceMedium metrics. |
| `sm-dashboard-builder` | Build accurate BI dashboards from SourceMedium BigQuery data, defaulting to portable HTML with SQL receipts and renderer-appropriate charts. |
| `sm-pipeline-builder` | Spec, build, validate, and operate bespoke data pipelines that land in customer-owned BigQuery datasets alongside SourceMedium data, or publish those tables back out to a system you own. |

## After Installing

Ask your coding agent questions like:

```
What was my revenue by channel last month?
```

```
Show me new customer acquisition by source over the past 30 days
```

```
What's my customer LTV by cohort?
```

Your agent will verify access, generate SQL, and return an auditable "SQL receipt".

For dashboard work, ask:

```
Build an HTML executive dashboard for net revenue, orders, AOV, channel mix,
ad spend, and MER for the last 30 days.
```

```
Create Metabase-ready cards for CAC, MER, spend, and revenue by channel.
```

(BI-tool handoffs such as Metabase query BigQuery directly, so they need direct
warehouse access, part of Pro.)

The dashboard skill should discover metadata, define metric contracts, dry-run
each BI query, execute bounded queries, and then build `dashboard.html` from a
manifest with chart specs, embedded data, QA notes, freshness, and SQL receipts.
The bundled HTML builder uses Vega-Lite for portability, but agents should use
Metabase/native BI settings or an existing app chart library when that is the
target.

Before a dashboard is shared, its manifest must pass strict validation, which
refuses unresolved `<project>`-style names, non-date freshness checks, and
failed tiles:

```bash
python skills/sm-dashboard-builder/scripts/validate_dashboard_manifest.py \
  dashboard_manifest.json --strict
```

Use
[dashboard_publish_checklist.md](skills/sm-dashboard-builder/assets/dashboard_publish_checklist.md)
as the final share/handoff checklist.

For hybrid analysis (joining your own tables in the warehouse needs direct
warehouse access, part of Pro), add a project-local `sourcemedium_custom_data.md` describing
your own tables' grain, join keys, date coverage, owner/source, caveats, and PII
columns before asking the agent to join them to SourceMedium data.

For bespoke pipeline work (needs direct warehouse access, part of Pro), ask:

```
Build a nightly pipeline that ingests our loyalty platform into our own
BigQuery datasets and joins point liability to SourceMedium revenue.
```

The pipeline skill writes a validated pipeline spec first (grain, keys,
cursor, windows, checks), then builds, validates with a canary plus
source-parity totals, and hands over a readiness checklist.

## What a New Agent Needs to Know

SourceMedium data is already modeled for analysis. A cold coding agent should not
guess table names, columns, categorical values, metric definitions, or warehouse
layout. It should:

1. Use the SourceMedium MCP if it is connected (every plan). With direct
   warehouse access (Pro), `gcloud`/`bq` also work; verify their auth first.
2. Resolve the warehouse names. A dedicated warehouse is the tenant's own
   project with `sm_metadata`, `sm_transformed_v2`, ...; the shared warehouse is
   `sourcemedium-bi` with `<tenant>_sm_metadata`, `<tenant>_sm_transformed_v2`,
   .... `get_data_context` reports them; with direct access, so does the
   doctor script.
3. Read `dim_data_dictionary` for available tables and freshness, and
   `dim_semantic_metric_catalog` for metric definitions, including each
   metric's `filter_condition` (its `calculation` column is documentation, not
   SQL).
4. Use `obt_orders`, `obt_order_lines`, `obt_customers`,
   `rpt_ad_performance_daily`, and the cohort LTV table for core analytics, and
   aggregate before dividing for every ratio.
5. Dry-run every new query and enforce a bytes-billed cap before execution.

```bash
# With direct warehouse access (Pro):
python skills/sm-bigquery-analyst/scripts/sm_bq_doctor.py --project <project>
```

Direct BigQuery access is part of Pro and comes from membership in your
SourceMedium workspace, not from your own Google Cloud admin; see the
[access guide](skills/sm-bigquery-analyst/assets/BIGQUERY_ACCESS_REQUEST_TEMPLATE.md).

## QA Harness

After editing any skill, run the offline package QA:

```bash
just ci        # or: python scripts/qa_all_skills.py --skip-cli-discovery
```

With live warehouse access (read-only):

```bash
just qa-live
```

`qa-live` runs every SQL example the skills ship against the demo warehouse
(dry-run, execute under a cap, require rows) and dry-runs them again against
SourceMedium's own shared-warehouse tenant, so a wrong column, a missing table,
a dataset name that only works on one layout, or a filter constant that matches
nothing fails QA. It also exercises the analyst scripts: the doctor, capped
discovery, cost-cap blocking, and truncation reporting.

The demo warehouse is fine for those checks. Do not use it to decide whether an
answer is *correct*: its values are obfuscated. Validate numbers against a real
tenant warehouse instead.

Per-skill QA:

```bash
python skills/sm-bigquery-analyst/scripts/qa_sm_bigquery_skill.py --project sm-democo
python skills/sm-dashboard-builder/scripts/qa_sm_dashboard_skill.py
python skills/sm-pipeline-builder/scripts/qa_sm_pipeline_skill.py
python scripts/qa_sql_examples.py --project sm-democo
```

The dashboard QA builds HTML from the template and proves `--strict` refuses
the template until its names are resolved. The pipeline QA covers package
shape, reference routing, a credential scan over the package, and the spec
validator's full accept/reject matrix; it also fuzzes every path in the spec
template with every wrong type, so a missing shape guard fails QA here instead
of surfacing as a traceback in front of an operator. When writing a real
pipeline, validate your per-pipeline spec copy, not the shipped template.

## Documentation

- [Agent Skills Overview](https://docs.sourcemedium.com/ai-analyst/agent-skills)
- [SM BigQuery Analyst](https://docs.sourcemedium.com/ai-analyst/agent-skills/sm-bigquery-analyst)
- [SM Dashboard Builder](https://docs.sourcemedium.com/ai-analyst/agent-skills/sm-dashboard-builder)
- [SM Pipeline Builder](https://docs.sourcemedium.com/ai-analyst/agent-skills/sm-pipeline-builder)
- [BigQuery Access](https://docs.sourcemedium.com/ai-analyst/agent-skills/bigquery-access-request-template)
- [Connect an AI assistant (MCP)](https://docs.sourcemedium.com/ai-analyst/connect-an-ai-assistant)
