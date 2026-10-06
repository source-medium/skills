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

# Live warehouse QA. The demo warehouse proves every shipped SQL example runs
# and returns rows on the dedicated layout; SourceMedium's own shared-lane
# tenant proves the same names resolve on the shared layout (dry-run only:
# that tenant has little data). Read-only; needs gcloud access to both.
qa-live:
    python3 scripts/qa_all_skills.py --skip-cli-discovery --project sm-democo
    python3 scripts/qa_all_skills.py --skip-cli-discovery --project sourcemedium-bi --tenant sourcemedium --names-only
