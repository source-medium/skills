# SourceMedium Agent Skills

Installable skills for coding agents that work with SourceMedium BigQuery data.

## Quick Start (Copy/Paste)

Copy this prompt and give it to your coding agent:

```
Install the SourceMedium BigQuery analyst skill and help me verify my setup:

1. Run: npx skills add source-medium/skills --skill sm-bigquery-analyst
2. Run the setup verification commands from the skill
3. Confirm my BigQuery access is working

My BigQuery project ID is: [YOUR_PROJECT_ID]
```

## Install

```bash
npx skills add source-medium/skills --skill sm-bigquery-analyst
```

To pin to a specific version: `npx skills add source-medium/skills@v1.0.1 --skill sm-bigquery-analyst`

See [Releases](https://github.com/source-medium/skills/releases) for available versions.

## Available Skills

| Skill | Description |
|-------|-------------|
| `sm-bigquery-analyst` | Query SourceMedium BigQuery safely. Emits SQL receipts. SELECT-only, cost-guarded. |

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

## Documentation

- [Agent Skills Overview](https://docs.sourcemedium.com/ai-analyst/agent-skills)
- [SM BigQuery Analyst](https://docs.sourcemedium.com/ai-analyst/agent-skills/sm-bigquery-analyst)
- [BigQuery Access Request Template](https://docs.sourcemedium.com/ai-analyst/agent-skills/bigquery-access-request-template)

## Releases

| Version | Notes |
|---------|-------|
| `v1.0.1` | Single skill, fixed SQL |
| `v1.0.0` | Initial release |
