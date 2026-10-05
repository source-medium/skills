#!/usr/bin/env python3
"""Run safe, cost-capped BigQuery SELECT queries for SourceMedium analysis.

Rows go to stdout. The receipt (status, dry-run bytes, statement type,
referenced tables, rows returned, truncation) goes to stderr as JSON.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import sys
from pathlib import Path

from sm_bq_common import DEFAULT_MAX_BYTES_BILLED, DEFAULT_MAX_ROWS, BqError, dry_run, execute

EXIT_MISSING_TOOL = 2
EXIT_UNSAFE_SQL = 3
EXIT_DRY_RUN_FAILED = 4
EXIT_COST_CAP = 5
EXIT_EXECUTION_FAILED = 6
EXIT_TRUNCATED = 7

BANNED_STATEMENTS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE|EXPORT|COPY|LOAD|GRANT|REVOKE|CALL|EXECUTE|DECLARE|SET|BEGIN)\b",
    re.IGNORECASE,
)
# One left-to-right pass over comments, strings, and backtick identifiers, so a
# quote inside a comment ("-- each store's orders") or a keyword inside a
# literal ('copy', `call`) is never mistaken for SQL.
TOKENS = re.compile(
    r"(?P<comment>--[^\n]*|#[^\n]*|/\*.*?\*/)"
    r"|(?P<literal>'''.*?'''|\"\"\".*?\"\"\"|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`[^`]*`)",
    re.DOTALL,
)


def strip_literals_and_comments(sql: str) -> str:
    return TOKENS.sub(lambda m: " " if m.group("comment") else "''", sql).strip()


def validate_sql(sql: str) -> None:
    """Offline pre-check. BigQuery's own statement type is checked after the dry-run."""
    normalized = strip_literals_and_comments(sql)
    if not normalized:
        raise ValueError("SQL is empty")
    if ";" in normalized.rstrip(";"):
        raise ValueError("Only a single SELECT or WITH statement is allowed")
    if not re.match(r"^\(*\s*(SELECT|WITH)\b", normalized, re.IGNORECASE):
        raise ValueError("Only SELECT or WITH queries are allowed")
    if BANNED_STATEMENTS.search(normalized):
        raise ValueError("Query contains a blocked DDL/DML/scripting statement")


def read_sql(args: argparse.Namespace) -> str:
    if args.sql_file:
        return Path(args.sql_file).read_text()
    if args.sql:
        return args.sql
    return sys.stdin.read()


def render(rows: list[dict], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(rows)
    if fmt == "prettyjson":
        return json.dumps(rows, indent=2)
    out = io.StringIO()
    fields: list[str] = []
    for row in rows:
        fields.extend(key for key in row if key not in fields)
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    return out.getvalue().rstrip("\n")


def emit_receipt(receipt: dict) -> None:
    print(json.dumps(receipt, indent=2), file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sql", help="SQL string. If omitted, stdin is used.")
    parser.add_argument("--sql-file", help="Path to a file containing SQL.")
    parser.add_argument("--project", help="BigQuery project that runs the job, such as sm-acme or sourcemedium-bi.")
    parser.add_argument("--location", help="BigQuery location, such as US.")
    parser.add_argument(
        "--maximum-bytes-billed",
        type=int,
        default=DEFAULT_MAX_BYTES_BILLED,
        help="Maximum bytes billed for execution. Default: 1 GiB.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=DEFAULT_MAX_ROWS,
        help=f"Rows to return. More rows than this exits {EXIT_TRUNCATED} with status truncated. Default: {DEFAULT_MAX_ROWS}.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only validate and estimate bytes.")
    parser.add_argument("--format", default="json", choices=["json", "csv", "prettyjson"], help="Row output format.")
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

    try:
        estimate = dry_run(args.project, args.location, sql)
    except BqError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_DRY_RUN_FAILED

    receipt = {**estimate, "maximum_bytes_billed": args.maximum_bytes_billed}
    if estimate["statement_type"] != "SELECT":
        emit_receipt({**receipt, "status": "rejected_statement_type"})
        print(f"Unsafe SQL rejected: BigQuery parsed a {estimate['statement_type']} statement", file=sys.stderr)
        return EXIT_UNSAFE_SQL
    if estimate["bytes_processed"] > args.maximum_bytes_billed:
        emit_receipt({**receipt, "status": "blocked_cost_cap"})
        return EXIT_COST_CAP
    if args.dry_run:
        emit_receipt({**receipt, "status": "validated"})
        return 0

    try:
        rows, truncated = execute(
            args.project,
            args.location,
            sql,
            max_bytes_billed=args.maximum_bytes_billed,
            max_rows=args.max_rows,
        )
    except BqError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_EXECUTION_FAILED

    print(render(rows, args.format))
    emit_receipt(
        {
            **receipt,
            "status": "truncated" if truncated else "executed",
            "rows_returned": len(rows),
            "truncated": truncated,
        }
    )
    return EXIT_TRUNCATED if truncated else 0


if __name__ == "__main__":
    raise SystemExit(main())
