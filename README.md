# SourceMedium Agent Skills

Installable skills for coding agents that work with SourceMedium BigQuery data.

## Install

```bash
# Install all skills
npx skills add source-medium/skills

# Install specific skill
npx skills add source-medium/skills --skill sm-bigquery-analyst
npx skills add source-medium/skills --skill sm-bigquery-analyst-manual
```

## Available Skills

| Skill | Description |
|-------|-------------|
| `sm-bigquery-analyst` | Query SourceMedium BigQuery safely. Emits SQL receipts. SELECT-only, cost-guarded. |
| `sm-bigquery-analyst-manual` | Manual-only version. Requires explicit `/sm-bigquery-analyst-manual` invocation. |

## Documentation

See [docs.sourcemedium.com/ai-analyst/agent-skills](https://docs.sourcemedium.com/ai-analyst/agent-skills) for full documentation.
