# Agent Compatibility

These skills are standard folder-based Agent Skills: each skill lives under
`skills/<skill-name>/` and contains a required `SKILL.md`.

## Recommended Install

Use the `skills` CLI when available:

```bash
npx skills add source-medium/skills --skill sm-bigquery-analyst
npx skills add source-medium/skills --skill sm-dashboard-builder
npx skills add source-medium/skills --skill sm-pipeline-builder
```

Update installed copies with:

```bash
npx skills update sm-bigquery-analyst -y
npx skills update sm-dashboard-builder -y
npx skills update sm-pipeline-builder -y
```

Use `--project` or `--global` when the agent supports both scopes and you need
to be explicit.

## Copy-Based Install

For agents that read local skill folders but do not use the `skills` CLI, copy
the skill directory into the agent's configured skill path:

```bash
mkdir -p .claude/skills
cp -R skills/sm-bigquery-analyst .claude/skills/
cp -R skills/sm-dashboard-builder .claude/skills/
cp -R skills/sm-pipeline-builder .claude/skills/
```

To update a copied skill, replace the copied folder with the latest folder from
this repository and rerun the relevant QA command.

After any update, run:

```bash
python scripts/qa_all_skills.py
```

When live demo BigQuery access is available:

```bash
python scripts/qa_all_skills.py --project sm-democo
```

This exercises connectivity, metadata discovery, dry-runs, and cost caps.
The demo warehouse's values are obfuscated, so never use it to confirm that
a number or metric definition is correct — use a real tenant warehouse.

## Agent Notes

- Claude Code and Claude-compatible clients usually read `SKILL.md` directly
  from configured skill directories.
- Codex/OpenAI-compatible clients may also read `agents/openai.yaml` for display
  metadata and default prompts.
- Cursor, Windsurf, OpenClaw-style clients, and other coding agents vary in
  their skill search paths. If automatic install is unavailable, use the
  copy-based install path.
- Scripts are optional helpers. The core instructions remain in `SKILL.md` and
  `references/`, but running scripts improves reliability and QA evidence.
