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


def validate_sql_offline() -> bool:
    """The offline SQL gate: literals never trip it, statements always do."""
    sys.path.insert(0, str(SCRIPTS))
    from sm_bq_query import validate_sql

    cases = [
        ("keywords inside literals accepted", "SELECT 'copy; update' AS a, `call` FROM t WHERE x = \"delete\"", True),
        ("leading parenthesis accepted", "(SELECT 1)", True),
        ("trailing semicolon accepted", "SELECT 1;", True),
        ("apostrophe inside a comment accepted", "-- each store's orders\nSELECT 1 FROM t WHERE c = 'x'", True),
        ("quote inside a block comment accepted", "/* it's fine */ SELECT 'a' AS b", True),
        ("comment marker inside a literal kept as a literal", "SELECT '--' AS a FROM t; DROP TABLE t", False),
        ("DML rejected", "DELETE FROM t WHERE TRUE", False),
        ("second statement rejected", "SELECT 1; DROP TABLE t", False),
        ("DDL after a comment rejected", "-- note\nCREATE TABLE t AS SELECT 1", False),
        ("scripting rejected", "SELECT 1 FROM t WHERE x IN (SELECT 1); EXECUTE IMMEDIATE 'DROP TABLE t'", False),
    ]
    ok = True
    for name, sql, accepted in cases:
        try:
            validate_sql(sql)
            passed = accepted
        except ValueError:
            passed = not accepted
        print(f"{'PASS' if passed else 'FAIL'} {name}")
        ok = ok and passed
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Optional live BigQuery project, such as sm-democo or sourcemedium-bi.")
    parser.add_argument("--tenant", help="Shared-lane tenant id, with --project sourcemedium-bi.")
    parser.add_argument("--location")
    args = parser.parse_args()

    checks: list[bool] = []
    checks.append(validate_skill_md())
    checks.append(validate_json_files())
    checks.append(run("scripts compile", [sys.executable, "-m", "py_compile", *map(str, SCRIPTS.glob("*.py"))]))
    checks.append(validate_sql_offline())

    for script in ["sm_bq_doctor.py", "sm_bq_discover.py", "sm_bq_query.py"]:
        checks.append(run(f"{script} --help", [sys.executable, str(SCRIPTS / script), "--help"]))

    if args.project:
        common = ["--project", args.project]
        if args.location:
            common += ["--location", args.location]
        resolve = ["--tenant", args.tenant] if args.tenant else []
        checks.append(run("live doctor", [sys.executable, str(SCRIPTS / "sm_bq_doctor.py"), *common, *resolve, "--json"]))
        checks.append(
            run(
                "live focused metric discovery",
                [
                    sys.executable,
                    str(SCRIPTS / "sm_bq_discover.py"),
                    *common,
                    *resolve,
                    "--metrics",
                    "--metric-search",
                    "revenue",
                    "--metric-limit",
                    "5",
                ],
            )
        )
        sys.path.insert(0, str(SCRIPTS))
        from sm_bq_common import resolve_layout

        datasets = resolve_layout(args.project, args.location, tenant=args.tenant)["datasets"]
        transformed = datasets["sm_transformed_v2"]
        # The dictionary always has bytes to scan, so a 1-byte cap must block it.
        dictionary_query = f"SELECT table_name FROM `{args.project}.{datasets['sm_metadata']}.dim_data_dictionary`"
        query = (
            "SELECT sm_channel, COUNT(sm_order_key) AS order_count "
            f"FROM `{args.project}.{transformed}.obt_orders` "
            "WHERE is_order_sm_valid = TRUE "
            "AND DATE(order_processed_at_local_datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) "
            "GROUP BY sm_channel ORDER BY order_count DESC LIMIT 10"
        )
        query_cmd = [sys.executable, str(SCRIPTS / "sm_bq_query.py"), *common]
        checks.append(run("live safe dry-run", [*query_cmd, "--dry-run", "--sql", query]))
        checks.append(
            run(
                "live cost cap blocks execution",
                [*query_cmd, "--dry-run", "--maximum-bytes-billed", "1", "--sql", dictionary_query],
                expect=5,
            )
        )
        checks.append(run("live bounded execution", [*query_cmd, "--sql", query]))
        checks.append(run("live SQL opening with a comment runs", [*query_cmd, "--sql", "-- note\n" + query]))
        checks.append(
            run(
                "live truncation is reported, not silent",
                [*query_cmd, "--max-rows", "2", "--sql", "SELECT x FROM UNNEST(GENERATE_ARRAY(1, 5)) AS x"],
                expect=7,
            )
        )

    passed = all(checks)
    print(f"\n{'PASS' if passed else 'FAIL'} qa_sm_bigquery_skill")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
