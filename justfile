# skills — task runner

# The deterministic package QA, the one `just ci skills` runs from the
# monorepo root: JSON and YAML validity, py_compile, SKILL.md frontmatter, and
# each skill's own validators. CLI discovery downloads `skills` through npx, so
# it is in `ci-network`; live warehouse QA stays explicit (`--project`).
ci:
    python3 scripts/qa_all_skills.py --skip-cli-discovery

# The `skills` CLI discovery check, through npx
ci-network:
    python3 scripts/qa_all_skills.py
