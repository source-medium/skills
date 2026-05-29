#!/usr/bin/env python3
"""QA harness for the SourceMedium BigQuery Analyst skill package."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run(name: str, cmd: list[str], stdin: str | None = None, expect: int = 0) -> bool:
    result = subprocess.run(
        cmd,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    ok = result.returncode == expect
    status = "PASS" if ok else "FAIL"
    print(f"{status} {name}")
    if not ok:
        print(f"  command: {' '.join(cmd)}")
        print(f"  expected exit: {expect}; actual: {result.returncode}")
        if result.stdout.strip():
            print(f"  stdout: {result.stdout.strip()[:1000]}")
        if result.stderr.strip():
            print(f"  stderr: {result.stderr.strip()[:1000]}")
    return ok


def validate_skill_md() -> bool:
    path = ROOT / "SKILL.md"
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    checks = [
        ("SKILL.md exists", path.exists()),
        ("frontmatter exists", bool(match)),
        ("name matches directory", "name: sm-bigquery-analyst" in text),
        ("description mentions SourceMedium", "SourceMedium" in text.split("---", 2)[1]),
        ("body references scripts", "scripts/sm_bq_doctor.py" in text and "scripts/sm_bq_query.py" in text),
    ]
    ok = True
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
        ok = ok and passed
    return ok


def validate_json_files() -> bool:
    ok = True
    for path in [ROOT / "evals" / "evals.json"]:
        try:
            json.loads(path.read_text())
            print(f"PASS valid JSON: {path.relative_to(ROOT)}")
        except Exception as exc:
            print(f"FAIL valid JSON: {path.relative_to(ROOT)}: {exc}")
            ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Optional live BigQuery project, such as sm-democo.")
    parser.add_argument("--metadata-dataset", default="sm_metadata")
    parser.add_argument("--transformed-dataset", default="sm_transformed_v2")
    parser.add_argument("--location")
    parser.add_argument("--live-execute", action="store_true", help="Execute one small live aggregate query.")
    args = parser.parse_args()

    checks: list[bool] = []
    checks.append(validate_skill_md())
    checks.append(validate_json_files())
    checks.append(run("scripts compile", [sys.executable, "-m", "py_compile", *map(str, SCRIPTS.glob("*.py"))]))

    for script in ["sm_bq_doctor.py", "sm_bq_discover.py", "sm_bq_query.py"]:
        checks.append(run(f"{script} --help", [str(SCRIPTS / script), "--help"]))

    checks.append(
        run(
            "unsafe SQL rejected",
            [str(SCRIPTS / "sm_bq_query.py"), "--dry-run"],
            stdin="DROP TABLE x",
            expect=3,
        )
    )

    if args.project:
        common = ["--project", args.project]
        if args.location:
            common += ["--location", args.location]
        checks.append(
            run(
                "live doctor",
                [
                    str(SCRIPTS / "sm_bq_doctor.py"),
                    *common,
                    "--metadata-dataset",
                    args.metadata_dataset,
                    "--transformed-dataset",
                    args.transformed_dataset,
                    "--json",
                ],
            )
        )
        checks.append(
            run(
                "live focused metric discovery",
                [
                    str(SCRIPTS / "sm_bq_discover.py"),
                    *common,
                    "--metadata-dataset",
                    args.metadata_dataset,
                    "--transformed-dataset",
                    args.transformed_dataset,
                    "--metrics",
                    "--metric-search",
                    "revenue",
                    "--metric-limit",
                    "5",
                ],
            )
        )
        query = (
            "SELECT sm_channel, COUNT(sm_order_key) AS order_count "
            f"FROM `{args.project}.{args.transformed_dataset}.obt_orders` "
            "WHERE is_order_sm_valid = TRUE "
            "AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) "
            "GROUP BY sm_channel ORDER BY order_count DESC LIMIT 10"
        )
        checks.append(run("live safe dry-run", [str(SCRIPTS / "sm_bq_query.py"), *common, "--dry-run", "--sql", query]))
        checks.append(
            run(
                "live cost cap blocks execution",
                [
                    str(SCRIPTS / "sm_bq_query.py"),
                    *common,
                    "--dry-run",
                    "--maximum-bytes-billed",
                    "1",
                    "--sql",
                    query,
                ],
                expect=5,
            )
        )
        if args.live_execute:
            checks.append(run("live bounded execution", [str(SCRIPTS / "sm_bq_query.py"), *common, "--sql", query]))

    passed = all(checks)
    print(f"\n{'PASS' if passed else 'FAIL'} qa_sm_bigquery_skill")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
