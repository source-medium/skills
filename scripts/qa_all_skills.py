#!/usr/bin/env python3
"""Run package-level QA for SourceMedium skills."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
QUICK_VALIDATE = Path(os.environ["SKILL_QUICK_VALIDATE"]) if os.environ.get("SKILL_QUICK_VALIDATE") else None


def run(cmd: list[str], *, cwd: Path = ROOT) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def validate_json_files() -> None:
    for path in sorted(ROOT.glob("skills/**/*.json")):
        json.loads(path.read_text(encoding="utf-8"))
        print(f"json ok: {path.relative_to(ROOT)}")


def validate_yaml_files() -> None:
    try:
        import yaml
    except Exception as exc:
        print(f"yaml validation skipped: PyYAML unavailable ({exc})")
        return
    for path in sorted(ROOT.glob("skills/**/agents/*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise AssertionError(f"YAML root must be an object: {path}")
        print(f"yaml ok: {path.relative_to(ROOT)}")


def py_compile_scripts() -> None:
    scripts = sorted(str(path.relative_to(ROOT)) for path in ROOT.glob("skills/**/scripts/*.py"))
    if scripts:
        run([sys.executable, "-m", "py_compile", *scripts])


def quick_validate_skills() -> None:
    for skill_dir in sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir()):
        if not (skill_dir / "SKILL.md").exists():
            continue
        basic_validate_skill(skill_dir)
        if QUICK_VALIDATE and QUICK_VALIDATE.exists():
            run([sys.executable, str(QUICK_VALIDATE), str(skill_dir)])


def basic_validate_skill(skill_dir: Path) -> None:
    skill_md = skill_dir / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AssertionError(f"{skill_md} must start with YAML frontmatter")
    try:
        _, frontmatter, body = text.split("---", 2)
    except ValueError as exc:
        raise AssertionError(f"{skill_md} has malformed frontmatter") from exc

    fields: dict[str, str] = {}
    current_key: str | None = None
    for line in frontmatter.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            fields[current_key] = value.strip().strip('"')
        elif current_key:
            fields[current_key] += " " + line.strip()

    if fields.get("name") != skill_dir.name:
        raise AssertionError(f"{skill_md} name must match directory")
    if not fields.get("description"):
        raise AssertionError(f"{skill_md} requires description")
    if not body.strip():
        raise AssertionError(f"{skill_md} requires body instructions")
    print(f"skill ok: {skill_dir.name}")


def package_specific_qa(project: str | None) -> None:
    dashboard_qa = SKILLS_DIR / "sm-dashboard-builder" / "scripts" / "qa_sm_dashboard_skill.py"
    if dashboard_qa.exists():
        run([sys.executable, str(dashboard_qa)])

    dashboard_validator = SKILLS_DIR / "sm-dashboard-builder" / "scripts" / "validate_dashboard_manifest.py"
    dashboard_manifest = SKILLS_DIR / "sm-dashboard-builder" / "assets" / "dashboard_manifest_template.json"
    dashboard_example = SKILLS_DIR / "sm-dashboard-builder" / "assets" / "examples" / "executive_overview_manifest.json"
    if dashboard_validator.exists():
        run([sys.executable, str(dashboard_validator), str(dashboard_manifest), "--strict"])
        run([sys.executable, str(dashboard_validator), str(dashboard_example), "--strict"])

    analyst_qa = SKILLS_DIR / "sm-bigquery-analyst" / "scripts" / "qa_sm_bigquery_skill.py"
    if analyst_qa.exists():
        cmd = [str(analyst_qa)]
        if project:
            cmd.extend(["--project", project])
        run(cmd)


def skill_cli_discovery() -> None:
    run(["npx", "skills", "add", ".", "--skill", "sm-bigquery-analyst", "--list"], cwd=ROOT)
    run(["npx", "skills", "add", ".", "--skill", "sm-dashboard-builder", "--list"], cwd=ROOT)


def cleanup_python_cache() -> None:
    for path in ROOT.glob("**/__pycache__"):
        if ".git" in path.parts:
            continue
        shutil.rmtree(path)
    pyc_files = [path for path in ROOT.glob("**/*.pyc") if ".git" not in path.parts]
    if pyc_files:
        raise AssertionError("Unexpected .pyc files remain: " + ", ".join(str(path) for path in pyc_files))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Optional BigQuery project for live analyst QA")
    parser.add_argument("--skip-cli-discovery", action="store_true", help="Skip npx skills discovery checks")
    args = parser.parse_args()

    atexit.register(cleanup_python_cache)
    quick_validate_skills()
    validate_json_files()
    validate_yaml_files()
    py_compile_scripts()
    package_specific_qa(args.project)
    if not args.skip_cli_discovery:
        skill_cli_discovery()
    cleanup_python_cache()
    print("All skill QA passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
