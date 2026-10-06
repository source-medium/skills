#!/usr/bin/env python3
"""End-to-end QA for the SourceMedium dashboard builder skill package."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def parse_frontmatter(skill_text: str) -> dict[str, str]:
    assert_true(skill_text.startswith("---\n"), "SKILL.md must start with YAML frontmatter")
    _, frontmatter, _ = skill_text.split("---", 2)
    values: dict[str, str] = {}
    current_key: str | None = None
    for line in frontmatter.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            values[current_key] = value.strip().strip('"')
        elif current_key:
            values[current_key] += " " + line.strip()
    return values


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def validate(path: Path, *, strict: bool) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "scripts/validate_dashboard_manifest.py", str(path)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def resolve_template(manifest: dict) -> dict:
    """What an agent does before publishing: real names and a real freshness check."""
    text = json.dumps(manifest).replace("<project>", "sm-acme").replace("<sm_transformed_v2>", "sm_transformed_v2")
    resolved = json.loads(text)
    for chart in resolved["charts"]:
        chart["query_metadata"]["freshness_checked_at"] = "2026-01-02"
    return resolved


def main() -> int:
    skill_md = ROOT / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(text)
    assert_true(frontmatter.get("name") == "sm-dashboard-builder", "Unexpected skill name")
    assert_true("dashboard" in frontmatter.get("description", "").lower(), "Description should mention dashboard use")
    assert_true("build_dashboard_html.py" in text, "Skill should document the HTML builder")
    assert_true("validate_dashboard_manifest.py" in text, "Skill should document manifest validation")
    assert_true("qa_sm_dashboard_skill.py" in text, "Skill should document its QA harness")

    manifest_path = ROOT / "assets" / "dashboard_manifest_template.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert_true(isinstance(manifest.get("metric_contracts"), list), "Manifest template requires metric contracts")
    assert_true(isinstance(manifest.get("charts"), list), "Manifest template requires charts")
    assert_true(manifest["charts"], "Manifest template should include one chart")
    assert_true("sql" in manifest["charts"][0], "Template chart requires SQL receipt")

    evals_path = ROOT / "evals" / "evals.json"
    if evals_path.exists():
        evals = json.loads(evals_path.read_text(encoding="utf-8"))
        assert_true(isinstance(evals.get("examples"), list), "evals.json examples must be a list")

    run([sys.executable, "scripts/build_dashboard_html.py", "--help"])
    run([sys.executable, "scripts/validate_dashboard_manifest.py", "--help"])
    run([sys.executable, "scripts/validate_dashboard_manifest.py", str(manifest_path)])
    run([sys.executable, "scripts/validate_dashboard_manifest.py", str(ROOT / "assets/examples/executive_overview_manifest.json")])

    # The template is a template: strict mode must refuse it until its names are resolved.
    template_strict = validate(manifest_path, strict=True)
    assert_true(template_strict.returncode != 0, "Strict validation must reject the unresolved template")
    assert_true("unresolved placeholders" in template_strict.stdout, "Strict rejection must name the placeholders")

    with tempfile.TemporaryDirectory() as tempdir:
        resolved = resolve_template(manifest)
        resolved_path = Path(tempdir) / "resolved.json"
        resolved_path.write_text(json.dumps(resolved), encoding="utf-8")
        resolved_strict = validate(resolved_path, strict=True)
        assert_true(resolved_strict.returncode == 0, f"Resolved template must pass strict: {resolved_strict.stdout}")

        out = Path(tempdir) / "dashboard.html"
        run([sys.executable, "scripts/build_dashboard_html.py", str(resolved_path), "--out", str(out), "--strict"])
        html = out.read_text(encoding="utf-8")
        assert_true("vegaEmbed" in html, "Dashboard HTML must call vegaEmbed")
        assert_true("SQL Receipts" in html, "Dashboard HTML must include SQL receipts")
        assert_true("chart-revenue_trend" in html, "Dashboard HTML must include the template chart id")
        assert_true("order_net_revenue" in html, "Dashboard HTML must preserve SQL receipt text")
        assert_true("Replace template data" in html, "Dashboard HTML must preserve QA notes")

        for name, chart_patch in (
            ("Unsafe SQL", {"sql": "DROP TABLE example"}),
            ("A failed QA status", {"query_metadata": dict(resolved["charts"][0]["query_metadata"], qa_status="fail")}),
            ("A non-date freshness check", {"query_metadata": dict(resolved["charts"][0]["query_metadata"], freshness_checked_at="soon")}),
        ):
            bad = dict(resolved, charts=[dict(resolved["charts"][0], **chart_patch)])
            bad_path = Path(tempdir) / "bad.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            assert_true(validate(bad_path, strict=True).returncode != 0, f"{name} should fail strict manifest validation")

    print("sm-dashboard-builder QA passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
