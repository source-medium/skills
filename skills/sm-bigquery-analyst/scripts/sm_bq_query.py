#!/usr/bin/env python3
"""Run safe, cost-capped BigQuery SELECT queries for SourceMedium analysis."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


EXIT_MISSING_TOOL = 2
EXIT_UNSAFE_SQL = 3
EXIT_DRY_RUN_FAILED = 4
EXIT_COST_CAP = 5
EXIT_EXECUTION_FAILED = 6

BANNED_STATEMENTS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE|EXPORT|COPY|LOAD|GRANT|REVOKE|CALL)\b",
    re.IGNORECASE,
)


def strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--.*?$", " ", sql, flags=re.MULTILINE)
    return sql.strip()


def validate_sql(sql: str) -> None:
    normalized = strip_comments(sql)
    if not normalized:
        raise ValueError("SQL is empty")
    if ";" in normalized.rstrip(";"):
        raise ValueError("Only a single SELECT or WITH statement is allowed")
    if not re.match(r"^(SELECT|WITH)\b", normalized, re.IGNORECASE):
        raise ValueError("Only SELECT or WITH queries are allowed")
    if BANNED_STATEMENTS.search(normalized):
        raise ValueError("Query contains a blocked DDL/DML/admin statement")


def bq_base(project: str | None, location: str | None) -> list[str]:
    cmd = ["bq"]
    if project:
        cmd.append(f"--project_id={project}")
    if location:
        cmd.append(f"--location={location}")
    return cmd


def run_command(cmd: list[str], sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd + [sql],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def parse_dry_run_bytes(output: str) -> int | None:
    match = re.search(r"will process ([0-9,]+) bytes", output)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def read_sql(args: argparse.Namespace) -> str:
    if args.sql_file:
        return Path(args.sql_file).read_text()
    if args.sql:
        return args.sql
    return sys.stdin.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql", help="SQL string. If omitted, stdin is used.")
    parser.add_argument("--sql-file", help="Path to a file containing SQL.")
    parser.add_argument("--project", help="BigQuery project ID, such as sm-acme.")
    parser.add_argument("--location", help="BigQuery location, such as US.")
    parser.add_argument(
        "--maximum-bytes-billed",
        type=int,
        default=1_073_741_824,
        help="Maximum bytes billed for execution. Default: 1 GiB.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only validate and estimate bytes.")
    parser.add_argument("--format", default="json", choices=["json", "csv", "prettyjson"], help="bq output format.")
    args = parser.parse_args()

    if not shutil.which("bq"):
        print("bq CLI not found on PATH", file=sys.stderr)
        return EXIT_MISSING_TOOL

    sql = read_sql(args)
    try:
        validate_sql(sql)
    except ValueError as exc:
        print(f"Unsafe SQL rejected: {exc}", file=sys.stderr)
        return EXIT_UNSAFE_SQL

    dry_cmd = bq_base(args.project, args.location) + [
        "query",
        "--use_legacy_sql=false",
        "--dry_run",
    ]
    dry_result = run_command(dry_cmd, sql)
    dry_output = (dry_result.stdout + dry_result.stderr).strip()
    if dry_result.returncode != 0:
        print(dry_output, file=sys.stderr)
        return EXIT_DRY_RUN_FAILED

    bytes_processed = parse_dry_run_bytes(dry_output)
    receipt = {
        "dry_run": True,
        "bytes_processed": bytes_processed,
        "maximum_bytes_billed": args.maximum_bytes_billed,
        "message": dry_output,
    }

    if bytes_processed is not None and bytes_processed > args.maximum_bytes_billed:
        print(json.dumps({**receipt, "status": "blocked_cost_cap"}, indent=2))
        return EXIT_COST_CAP

    if args.dry_run:
        print(json.dumps({**receipt, "status": "validated"}, indent=2))
        return 0

    exec_cmd = bq_base(args.project, args.location) + [
        "query",
        "--use_legacy_sql=false",
        f"--maximum_bytes_billed={args.maximum_bytes_billed}",
        f"--format={args.format}",
        "--quiet",
    ]
    exec_result = run_command(exec_cmd, sql)
    if exec_result.returncode != 0:
        print(exec_result.stderr.strip() or exec_result.stdout.strip(), file=sys.stderr)
        return EXIT_EXECUTION_FAILED

    print(exec_result.stdout.strip())
    print(
        json.dumps(
            {
                "status": "executed",
                "bytes_processed": bytes_processed,
                "maximum_bytes_billed": args.maximum_bytes_billed,
            },
            indent=2,
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
