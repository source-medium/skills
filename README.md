# SourceMedium Agent Skills

Installable skills for coding agents that work with SourceMedium BigQuery data.

`sm` is the SourceMedium shorthand. Skills use `sm-<job>` names so Claude Code,
Codex, OpenClaw-style agents, and other skill clients can route to them
predictably while display metadata spells out the SourceMedium brand.

## Quick Start (Copy/Paste)

Copy this prompt and give it to your coding agent:

```
Install and use the SourceMedium BigQuery Analyst skill.

Context:
- SourceMedium hosts analytics-ready ecommerce data in BigQuery.
- My SourceMedium project ID is: [YOUR_PROJECT_ID]
- Default datasets are sm_metadata and sm_transformed_v2 unless I provide custom dataset names.
- I may also have my own BigQuery tables that I want to join to SourceMedium data.

Tasks:
1. Install: npx skills add source-medium/skills --skill sm-bigquery-analyst
2. Run the skill's setup verification.
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

The dashboard skill should discover metadata, define metric contracts, dry-run
each BI query, execute bounded queries, and then build `dashboard.html` from a
manifest with chart specs, embedded data, QA notes, freshness, and SQL receipts.
The bundled HTML builder uses Vega-Lite for portability, but agents should use
Metabase/native BI settings or an existing app chart library when that is the
target.

For publishable dashboards, agents should validate the manifest in strict mode
before rendering or handoff:

```bash
python skills/sm-dashboard-builder/scripts/validate_dashboard_manifest.py \
  skills/sm-dashboard-builder/assets/dashboard_manifest_template.json \
  --strict
```

Use
[dashboard_publish_checklist.md](skills/sm-dashboard-builder/assets/dashboard_publish_checklist.md)
as the final share/handoff checklist.

For hybrid analysis, add a project-local `sourcemedium_custom_data.md` describing
your own tables' grain, join keys, date coverage, owner/source, caveats, and PII
columns before asking the agent to join them to SourceMedium data.

For bespoke pipeline work, ask:

```
Build a nightly pipeline that ingests our loyalty platform into our own
BigQuery datasets and joins point liability to SourceMedium revenue.
```

The pipeline skill writes a validated pipeline spec first (grain, keys,
cursor, windows, checks), then builds, validates with a canary plus
source-parity totals, and hands over a readiness checklist.

## What a New Agent Needs to Know

SourceMedium data is already modeled for analysis. A cold coding agent should not
guess table names, columns, categorical values, metric definitions, or tenant
layout. It should:

1. Verify `gcloud`/`bq` auth and the active BigQuery project.
2. Read `sm_metadata.dim_data_dictionary` to discover available tables and freshness.
3. Read `sm_metadata.dim_semantic_metric_catalog` to resolve metric names and aliases.
4. Use `sm_transformed_v2` for core analytics tables such as `obt_orders`,
   `obt_order_lines`, `obt_customers`, `rpt_ad_performance_daily`, and
   `rpt_cohort_ltv_*`.
5. Dry-run every new query and enforce a bytes-billed cap before execution.

Most tenants use datasets named `sm_metadata` and `sm_transformed_v2`. If your
warehouse uses tenant-prefixed datasets in a shared project, pass those dataset
names to the helper scripts:

```bash
python skills/sm-bigquery-analyst/scripts/sm_bq_doctor.py \
  --project <project> \
  --metadata-dataset <tenant>_sm_metadata \
  --transformed-dataset <tenant>_sm_transformed_v2
```

## QA Harness

After editing any skill, run the package QA:

```bash
python scripts/qa_all_skills.py
```

With live demo access:

```bash
python scripts/qa_all_skills.py --project sm-democo
```

For targeted analyst QA:

```bash
python skills/sm-bigquery-analyst/scripts/qa_sm_bigquery_skill.py
```

With live demo access:

```bash
python skills/sm-bigquery-analyst/scripts/qa_sm_bigquery_skill.py --project sm-democo
```

The harness validates package shape, script syntax, help output, unsafe-SQL
rejection, optional live metadata discovery, dry-runs, and cost-cap blocking.
`--project` here is a connectivity and schema smoke test, so the demo
warehouse is fine for it. Do not use the demo warehouse to check whether an
answer is *correct* — its values are obfuscated. Validate numbers against a
real tenant warehouse instead.

For dashboard package QA:

```bash
python skills/sm-dashboard-builder/scripts/qa_sm_dashboard_skill.py
python skills/sm-dashboard-builder/scripts/validate_dashboard_manifest.py \
  skills/sm-dashboard-builder/assets/dashboard_manifest_template.json \
  --strict
python skills/sm-dashboard-builder/scripts/build_dashboard_html.py \
  skills/sm-dashboard-builder/assets/dashboard_manifest_template.json \
  --out /tmp/sm-dashboard.html
```

For pipeline package QA:

```bash
python skills/sm-pipeline-builder/scripts/qa_sm_pipeline_skill.py
python skills/sm-pipeline-builder/scripts/validate_pipeline_spec.py \
  skills/sm-pipeline-builder/assets/pipeline_spec_template.yaml \
  --strict
```

The harness covers package shape, reference routing, a credential scan over
the package, and the spec validator's full accept/reject matrix. It also
fuzzes every path in the spec template with every wrong type, so a missing
shape guard fails QA here instead of surfacing as a traceback in front of an
operator. When writing a real pipeline, validate your per-pipeline spec copy,
not the shipped template.

## Documentation

- [Agent Skills Overview](https://docs.sourcemedium.com/ai-analyst/agent-skills)
- [SM BigQuery Analyst](https://docs.sourcemedium.com/ai-analyst/agent-skills/sm-bigquery-analyst)
- [SM Dashboard Builder](https://docs.sourcemedium.com/ai-analyst/agent-skills/sm-dashboard-builder)
- [BigQuery Access Request Template](https://docs.sourcemedium.com/ai-analyst/agent-skills/bigquery-access-request-template)
