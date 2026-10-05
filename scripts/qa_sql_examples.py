#!/usr/bin/env python3
"""Run every SourceMedium SQL example the skills ship against a live warehouse.

Each example is dry-run (it must parse as a SELECT over real tables and
columns) and then executed under a bytes cap; its first row must carry at least
one non-NULL, non-zero value.
That catches a wrong column, a table that does not exist, and a filter
constant that matches nothing, none of which a package-shape check can see.

Examples use lane-neutral names, which this script resolves the same way the
analyst scripts do:

    `<project>.<sm_transformed_v2>.obt_orders`

Examples that name operator-owned tables (`<your_project>`, `<join_key>`, ...)
cannot run here and are skipped by name.

    python scripts/qa_sql_examples.py --project sm-democo
    python scripts/qa_sql_examples.py --project sourcemedium-bi --tenant <tenant> --names-only

Use --names-only (dry-run only) against a tenant whose data is sparse: it still
proves every table, column, and dataset name resolves on that layout.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "sm-bigquery-analyst" / "scripts"))

from sm_bq_common import BqError, dry_run, execute, resolve_layout  # noqa: E402

PLACEHOLDER_RE = re.compile(r"<[a-z_][a-z0-9_]*>")
# Names an operator fills in from their own warehouse. An example that uses one
# has nothing to run against here. Any other unresolved name is a bug.
OPERATOR_PLACEHOLDERS = {
    "<your_project>", "<your_dataset>", "<your_table>", "<join_key>", "<dim_col>", "<metric>",
    "<custom_metric>", "<store_col>", "<source_system_col>", "<order_id_col>",
}
MAX_BYTES = 2 * 1024**3


def sql_examples() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted((ROOT / "skills").rglob("*")):
        rel = path.relative_to(ROOT)
        if path.suffix == ".md":
            text = path.read_text(encoding="utf-8")
            for i, block in enumerate(re.findall(r"```sql\n(.*?)```", text, re.DOTALL)):
                for j, stmt in enumerate(split_statements(block)):
                    found.append((f"{rel} sql block {i + 1}.{j + 1}", stmt))
        elif path.suffix == ".json":
            for where, sql in json_sql(json.loads(path.read_text(encoding="utf-8")), ""):
                found.append((f"{rel}:{where}", sql))
    return found


def json_sql(node: object, where: str):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("sql", "native_sql") and isinstance(value, str):
                yield f"{where}.{key}", value
            else:
                yield from json_sql(value, f"{where}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from json_sql(value, f"{where}[{i}]")


def split_statements(block: str) -> list[str]:
    # A block holds one query, or several separated by `;` or by a blank line
    # before a `--` comment header.
    statements = []
    for part in re.split(r";\s*\n|\n\s*\n(?=\s*--)", block):
        body = re.sub(r"--.*?$", "", part, flags=re.MULTILINE).strip().rstrip(";")
        if re.match(r"^(SELECT|WITH)\b", body, re.IGNORECASE) and re.search(r"\bFROM\b", body, re.IGNORECASE):
            statements.append(body)
    return statements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="Warehouse project to test against.")
    parser.add_argument("--tenant", help="Shared-lane tenant id.")
    parser.add_argument("--location")
    parser.add_argument("--names-only", action="store_true", help="Dry-run only; do not require rows.")
    args = parser.parse_args()

    layout = resolve_layout(args.project, args.location, tenant=args.tenant)
    names = {"<project>": args.project, **{f"<{k}>": v for k, v in layout["datasets"].items()}}
    mode = "dry-run only" if args.names_only else "dry-run and execute"
    print(f"SQL examples against {args.project} ({layout['lane']} lane, {mode})")

    failures = skipped = passed = 0
    for where, sql in sql_examples():
        if "..." in sql:
            skipped += 1
            continue
        # Metabase native SQL carries template variables; give them a sample window.
        sql = sql.replace("{{start_date}}", "DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)").replace("{{end_date}}", "CURRENT_DATE()")
        resolved = sql
        for placeholder, value in names.items():
            resolved = resolved.replace(placeholder, value)
        leftover = set(PLACEHOLDER_RE.findall(resolved))
        if leftover - OPERATOR_PLACEHOLDERS:
            failures += 1
            print(f"FAIL {where}\n  unknown placeholder(s): {', '.join(sorted(leftover - OPERATOR_PLACEHOLDERS))}")
            continue
        if leftover:
            skipped += 1
            continue
        try:
            estimate = dry_run(args.project, args.location, resolved)
            if estimate["statement_type"] != "SELECT":
                raise BqError(f"statement type {estimate['statement_type']}")
            if args.names_only:
                passed += 1
                continue
            rows, _ = execute(args.project, args.location, resolved, max_bytes_billed=MAX_BYTES, max_rows=1)
            # A scalar aggregate returns one row even when its filter matches
            # nothing, so the row must also carry a non-NULL, non-zero value.
            if not rows or not any(v not in (None, "0", "0.0", 0) for v in rows[0].values()):
                raise BqError("returned no rows or only NULL/zero: a filter constant or table matches nothing here")
        except BqError as exc:
            failures += 1
            print(f"FAIL {where}\n  {str(exc).splitlines()[-1][:400]}")
            continue
        passed += 1

    print(f"\n{passed} passed, {failures} failed, {skipped} skipped (operator-owned or illustrative)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
