# skills — task runner

# The QA validates YAML and runs the pipeline skill's validator, and both need
# PyYAML. uv supplies it, so a recipe never depends on which packages the
# machine's python3 happens to have (without it the YAML check is skipped and
# the pipeline validator fails).
python := "uv run --no-project --with pyyaml python"

# The deterministic package QA, the one `just ci skills` runs from the
# monorepo root: JSON and YAML validity, py_compile, SKILL.md frontmatter, and
# each skill's own validators. CLI discovery downloads `skills` through npx, so
# it is in `ci-network`; live warehouse QA stays explicit (`--project`).
ci:
    {{python}} scripts/qa_all_skills.py --skip-cli-discovery

# The `skills` CLI discovery check, through npx
ci-network:
    {{python}} scripts/qa_all_skills.py

# Live warehouse QA. The demo warehouse proves every shipped SQL example runs
# and returns rows on the dedicated layout; SourceMedium's own shared-lane
# tenant proves the same names resolve on the shared layout (dry-run only:
# that tenant has little data). Read-only; needs gcloud access to both.
qa-live:
    {{python}} scripts/qa_all_skills.py --skip-cli-discovery --project sm-democo
    {{python}} scripts/qa_all_skills.py --skip-cli-discovery --project sourcemedium-bi --tenant sourcemedium --names-only
