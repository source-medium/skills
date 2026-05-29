#!/usr/bin/env python3
"""Discover SourceMedium BigQuery tables, metrics, stores, schemas, and values."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys


EXIT_MISSING_TOOL = 2
EXIT_QUERY_FAILED = 3


def run_bq(project: str, location: str | None, sql: str) -> tuple[int, str]:
    cmd = ["bq", f"--project_id={project}"]
    if location:
        cmd.append(f"--location={location}")
    cmd += ["query", "--use_legacy_sql=false", "--format=json", "--quiet", sql]
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        return result.returncode, result.stderr.strip() or result.stdout.strip()
    return 0, result.stdout.strip()


def fetch_rows(project: str, location: str | None, sql: str) -> list[dict[str, object]]:
    code, output = run_bq(project, location, sql)
    if code != 0:
        raise RuntimeError(output)
    if not output:
        return []
    return json.loads(output)


def print_section(title: str, body: str) -> None:
    print(f"\n## {title}\n")
    if not body:
        print("_No rows returned._")
        return
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        print(body)
        return
    if not rows:
        print("_No rows returned._")
        return
    print(json.dumps(rows, indent=2))


def query_or_exit(project: str, location: str | None, title: str, sql: str) -> None:
    code, output = run_bq(project, location, sql)
    if code != 0:
        print(f"{title} failed:\n{output}", file=sys.stderr)
        raise SystemExit(EXIT_QUERY_FAILED)
    print_section(title, output)


def metadata_columns(project: str, metadata_dataset: str, location: str | None) -> set[str]:
    rows = fetch_rows(
        project,
        location,
        f"""
SELECT column_name
FROM `{project}.{metadata_dataset}.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'dim_data_dictionary'
""".strip(),
    )
    return {str(row["column_name"]) for row in rows}


def table_discovery_sql(project: str, metadata_dataset: str, columns: set[str]) -> str:
    description_expr = (
        "ANY_VALUE(table_description) AS table_description"
        if "table_description" in columns
        else "CAST(NULL AS STRING) AS table_description"
    )
    has_data_expr = (
        "LOGICAL_OR(COALESCE(table_has_data, FALSE)) AS table_has_data"
        if "table_has_data" in columns
        else "CAST(NULL AS BOOL) AS table_has_data"
    )
    fresh_expr = (
        "LOGICAL_OR(COALESCE(table_has_fresh_data_14d, FALSE)) AS table_has_fresh_data_14d"
        if "table_has_fresh_data_14d" in columns
        else "CAST(NULL AS BOOL) AS table_has_fresh_data_14d"
    )
    last_date_expr = (
        "MAX(table_last_data_date) AS table_last_data_date"
        if "table_last_data_date" in columns
        else "CAST(NULL AS DATE) AS table_last_data_date"
    )
    return f"""
SELECT
  dataset_name,
  table_name,
  {description_expr},
  {has_data_expr},
  {fresh_expr},
  {last_date_expr}
FROM `{project}.{metadata_dataset}.dim_data_dictionary`
WHERE table_name IS NOT NULL
GROUP BY dataset_name, table_name
ORDER BY dataset_name, table_name
""".strip()


def categorical_sql(project: str, table_ref: str, column: str) -> str:
    return f"""
SELECT `{column}` AS value, COUNT(*) AS row_count
FROM `{table_ref}`
GROUP BY value
ORDER BY row_count DESC
LIMIT 50
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="SourceMedium BigQuery project ID, such as sm-acme.")
    parser.add_argument("--metadata-dataset", default="sm_metadata", help="Metadata dataset. Default: sm_metadata.")
    parser.add_argument(
        "--transformed-dataset",
        default="sm_transformed_v2",
        help="Transformed analytics dataset. Default: sm_transformed_v2.",
    )
    parser.add_argument("--location", help="BigQuery location, such as US.")
    parser.add_argument("--tables", action="store_true", help="Discover SourceMedium tables and freshness.")
    parser.add_argument("--metrics", action="store_true", help="Discover semantic metric catalog entries.")
    parser.add_argument("--metric-search", help="Filter metrics by name, label, description, category, or model.")
    parser.add_argument("--metric-limit", type=int, default=100, help="Maximum metrics to return. Default: 100.")
    parser.add_argument("--stores", action="store_true", help="Discover store IDs from obt_orders.")
    parser.add_argument("--schema", help="Discover schema for dataset.table or project.dataset.table.")
    parser.add_argument(
        "--categorical",
        action="append",
        default=[],
        help="Discover value distribution for dataset.table.column or project.dataset.table.column. Repeatable.",
    )
    args = parser.parse_args()

    if not shutil.which("bq"):
        print("bq CLI not found on PATH", file=sys.stderr)
        return EXIT_MISSING_TOOL

    if not any([args.tables, args.metrics, args.stores, args.schema, args.categorical]):
        args.tables = args.metrics = args.stores = True

    if args.tables:
        try:
            columns = metadata_columns(args.project, args.metadata_dataset, args.location)
        except RuntimeError as exc:
            print(f"Metadata column discovery failed:\n{exc}", file=sys.stderr)
            return EXIT_QUERY_FAILED
        query_or_exit(
            args.project,
            args.location,
            "Available SourceMedium tables",
            table_discovery_sql(args.project, args.metadata_dataset, columns),
        )

    if args.metrics:
        metric_where = ""
        if args.metric_search:
            escaped = args.metric_search.replace("\\", "\\\\").replace("'", "\\'")
            metric_where = f"""
WHERE INSTR(
  LOWER(CONCAT(
    COALESCE(metric_name, ''), ' ',
    COALESCE(metric_label, ''), ' ',
    COALESCE(metric_description, ''), ' ',
    COALESCE(metric_category, ''), ' ',
    COALESCE(semantic_model_name, '')
  )),
  LOWER('{escaped}')
) > 0
""".strip()
        query_or_exit(
            args.project,
            args.location,
            "Semantic metrics",
            f"""
SELECT
  metric_name,
  metric_label,
  metric_type,
  metric_category,
  semantic_model_name,
  metric_description,
  calculation
FROM `{args.project}.{args.metadata_dataset}.dim_semantic_metric_catalog`
{metric_where}
ORDER BY metric_category, metric_name
LIMIT {max(1, min(args.metric_limit, 1000))}
""".strip(),
        )

    if args.stores:
        query_or_exit(
            args.project,
            args.location,
            "Store IDs",
            f"""
SELECT sm_store_id, COUNT(*) AS order_count
FROM `{args.project}.{args.transformed_dataset}.obt_orders`
WHERE is_order_sm_valid = TRUE
GROUP BY sm_store_id
ORDER BY order_count DESC
""".strip(),
        )

    if args.schema:
        parts = args.schema.split(".")
        if len(parts) == 2:
            schema_project, dataset, table = args.project, parts[0], parts[1]
        elif len(parts) == 3:
            schema_project, dataset, table = parts
        else:
            print("--schema must be dataset.table or project.dataset.table", file=sys.stderr)
            return EXIT_QUERY_FAILED
        query_or_exit(
            schema_project,
            args.location,
            f"Schema for {schema_project}.{dataset}.{table}",
            f"""
SELECT column_name, data_type, is_nullable, ordinal_position
FROM `{schema_project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = '{table}'
ORDER BY ordinal_position
""".strip(),
        )

    for spec in args.categorical:
        parts = spec.split(".")
        if len(parts) == 3:
            cat_project = args.project
            dataset, table, column = parts
        elif len(parts) == 4:
            cat_project, dataset, table, column = parts
        else:
            print("--categorical must be dataset.table.column or project.dataset.table.column", file=sys.stderr)
            return EXIT_QUERY_FAILED
        table_ref = f"{cat_project}.{dataset}.{table}"
        query_or_exit(cat_project, args.location, f"Values for {table_ref}.{column}", categorical_sql(cat_project, table_ref, column))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
