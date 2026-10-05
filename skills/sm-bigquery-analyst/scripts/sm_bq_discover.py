#!/usr/bin/env python3
"""Discover SourceMedium BigQuery tables, metrics, stores, schemas, and values.

Every query is capped by --maximum-bytes-billed, and every section says when
it hit --max-rows instead of silently stopping there.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from sm_bq_common import DEFAULT_MAX_BYTES_BILLED, BqError, execute, resolve_layout

EXIT_MISSING_TOOL = 2
EXIT_QUERY_FAILED = 3

METRIC_COLUMNS = (
    "metric_name",
    "metric_label",
    "metric_type",
    "metric_category",
    "semantic_model_name",
    "underlying_model",
    "metric_description",
    "calculation",
    "has_filter",
    "filter_condition",
    "dependent_metrics",
    "preferred_metric_name",
)


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def ident(value: str) -> str:
    if "`" in value:
        raise ValueError(f"Invalid identifier: {value}")
    return f"`{value}`"


def query_section(args: argparse.Namespace, project: str, title: str, sql: str, max_rows: int) -> None:
    try:
        rows, truncated = execute(
            project, args.location, sql, max_bytes_billed=args.maximum_bytes_billed, max_rows=max_rows
        )
    except BqError as exc:
        print(f"{title} failed:\n{exc}", file=sys.stderr)
        raise SystemExit(EXIT_QUERY_FAILED)
    print(f"\n## {title}\n")
    if truncated:
        print(f"_Truncated at {max_rows} rows; narrow the request or raise the limit._\n")
    print(json.dumps(rows, indent=2) if rows else "_No rows returned._")


def metadata_columns(args: argparse.Namespace, metadata: str) -> set[str]:
    rows, _ = execute(
        args.project,
        args.location,
        f"SELECT column_name FROM {ident(f'{args.project}.{metadata}.INFORMATION_SCHEMA.COLUMNS')} "
        "WHERE table_name = 'dim_semantic_metric_catalog'",
        max_bytes_billed=args.maximum_bytes_billed,
        max_rows=500,
    )
    return {str(row["column_name"]) for row in rows}


def table_discovery_sql(project: str, metadata: str) -> str:
    # The dictionary has one row per store x dataset x table x column; fold it to tables.
    return f"""
SELECT
  dataset_name,
  table_name,
  ANY_VALUE(table_description) AS table_description,
  LOGICAL_OR(COALESCE(table_has_data, FALSE)) AS table_has_data,
  LOGICAL_OR(COALESCE(table_has_fresh_data_14d, FALSE)) AS table_has_fresh_data_14d,
  MAX(table_last_data_date) AS table_last_data_date
FROM {ident(f'{project}.{metadata}.dim_data_dictionary')}
WHERE table_name IS NOT NULL
GROUP BY dataset_name, table_name
ORDER BY dataset_name, table_name
""".strip()


def metric_discovery_sql(project: str, metadata: str, columns: set[str], search: str | None, limit: int) -> str:
    selected = ",\n  ".join(c if c in columns else f"CAST(NULL AS STRING) AS {c}" for c in METRIC_COLUMNS)
    where = ""
    if search:
        haystack = ", ' ', ".join(
            f"COALESCE(CAST({c} AS STRING), '')"
            for c in ("metric_name", "metric_label", "metric_description", "metric_category", "semantic_model_name")
            if c in columns
        )
        where = f"WHERE INSTR(LOWER(CONCAT({haystack})), LOWER({sql_string(search)})) > 0"
    return f"""
SELECT
  {selected}
FROM {ident(f'{project}.{metadata}.dim_semantic_metric_catalog')}
{where}
ORDER BY metric_category, metric_name
LIMIT {limit + 1}
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="Warehouse project, such as sm-acme or sourcemedium-bi.")
    parser.add_argument("--tenant", help="Shared-lane tenant id; datasets become <tenant>_sm_*.")
    parser.add_argument("--metadata-dataset", help="Metadata dataset. Default: resolved from the project.")
    parser.add_argument("--transformed-dataset", help="Transformed dataset. Default: resolved from the project.")
    parser.add_argument("--location", help="BigQuery location, such as US.")
    parser.add_argument(
        "--maximum-bytes-billed",
        type=int,
        default=DEFAULT_MAX_BYTES_BILLED,
        help="Bytes cap applied to every discovery query. Default: 1 GiB.",
    )
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
        help="Value distribution for dataset.table.column or project.dataset.table.column. Repeatable.",
    )
    parser.add_argument(
        "--days",
        type=int,
        help="With --categorical, count only rows whose DATE(<--date-column>) is in the last N days.",
    )
    parser.add_argument("--date-column", help="Date or timestamp column that --days filters on.")
    args = parser.parse_args()

    if not shutil.which("bq"):
        print("bq CLI not found on PATH", file=sys.stderr)
        return EXIT_MISSING_TOOL
    if bool(args.days) != bool(args.date_column):
        print("--days and --date-column go together", file=sys.stderr)
        return EXIT_QUERY_FAILED

    if not any([args.tables, args.metrics, args.stores, args.schema, args.categorical]):
        args.tables = args.metrics = args.stores = True

    # Only the tables, metrics, and stores sections read SourceMedium's datasets;
    # --schema and --categorical name theirs, so they never depend on resolution.
    if args.tables or args.metrics or args.stores:
        try:
            layout = resolve_layout(
                args.project,
                args.location,
                tenant=args.tenant,
                metadata_dataset=args.metadata_dataset,
                transformed_dataset=args.transformed_dataset,
            )
        except BqError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_QUERY_FAILED
        metadata = layout["datasets"]["sm_metadata"]
        transformed = layout["datasets"]["sm_transformed_v2"]
        print(f"# SourceMedium discovery: {args.project} ({layout['lane']} lane)")
        print(f"\nDatasets: {json.dumps(layout['datasets'])}")

    if args.tables:
        query_section(args, args.project, "Available SourceMedium tables", table_discovery_sql(args.project, metadata), 5000)

    if args.metrics:
        try:
            columns = metadata_columns(args, metadata)
        except BqError as exc:
            print(f"Metric catalog column discovery failed:\n{exc}", file=sys.stderr)
            return EXIT_QUERY_FAILED
        limit = max(1, min(args.metric_limit, 1000))
        query_section(
            args,
            args.project,
            "Semantic metrics",
            metric_discovery_sql(args.project, metadata, columns, args.metric_search, limit),
            limit,
        )
        print(
            "\n_`calculation` is documentation, not runnable SQL. Ratios are numerator / denominator "
            "metric names; a metric with has_filter = true applies `filter_condition`, whose column "
            "names can be internal ones (valid_order_sequence is published as sm_valid_order_sequence): "
            "check them against the table. Rebuild from dependent_metrics, filters included, "
            "aggregating before dividing._"
        )

    if args.stores:
        query_section(
            args,
            args.project,
            "Store IDs",
            f"""
SELECT sm_store_id, COUNT(*) AS order_count
FROM {ident(f'{args.project}.{transformed}.obt_orders')}
WHERE is_order_sm_valid = TRUE
GROUP BY sm_store_id
ORDER BY order_count DESC
""".strip(),
            100,
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
        query_section(
            args,
            schema_project,
            f"Schema for {schema_project}.{dataset}.{table}",
            f"""
SELECT column_name, data_type, is_nullable, ordinal_position
FROM {ident(f'{schema_project}.{dataset}.INFORMATION_SCHEMA.COLUMNS')}
WHERE table_name = {sql_string(table)}
ORDER BY ordinal_position
""".strip(),
            2000,
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
        where = (
            f"WHERE DATE({ident(args.date_column)}) >= DATE_SUB(CURRENT_DATE(), INTERVAL {int(args.days)} DAY)"
            if args.days
            else ""
        )
        query_section(
            args,
            cat_project,
            f"Values for {cat_project}.{dataset}.{table}.{column}",
            f"""
SELECT {ident(column)} AS value, COUNT(*) AS row_count
FROM {ident(f'{cat_project}.{dataset}.{table}')}
{where}
GROUP BY value
ORDER BY row_count DESC
""".strip(),
            50,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
