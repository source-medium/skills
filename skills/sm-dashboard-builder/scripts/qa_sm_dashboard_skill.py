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
    run([sys.executable, "scripts/validate_dashboard_manifest.py", str(manifest_path), "--strict"])

    with tempfile.TemporaryDirectory() as tempdir:
        out = Path(tempdir) / "dashboard.html"
        run([sys.executable, "scripts/build_dashboard_html.py", str(manifest_path), "--out", str(out), "--strict"])
        html = out.read_text(encoding="utf-8")
        assert_true("vegaEmbed" in html, "Dashboard HTML must call vegaEmbed")
        assert_true("SQL Receipts" in html, "Dashboard HTML must include SQL receipts")
        assert_true("chart-revenue_trend" in html, "Dashboard HTML must include the template chart id")
        assert_true("order_net_revenue" in html, "Dashboard HTML must preserve SQL receipt text")
        assert_true("Replace template data" in html, "Dashboard HTML must preserve QA notes")

        bad_manifest = dict(manifest)
        bad_manifest["charts"] = [dict(manifest["charts"][0], sql="DROP TABLE example")]
        bad_path = Path(tempdir) / "bad.json"
        bad_path.write_text(json.dumps(bad_manifest), encoding="utf-8")
        failed = subprocess.run(
            [sys.executable, "scripts/validate_dashboard_manifest.py", str(bad_path), "--strict"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert_true(failed.returncode != 0, "Unsafe SQL should fail strict manifest validation")

    print("sm-dashboard-builder QA passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
