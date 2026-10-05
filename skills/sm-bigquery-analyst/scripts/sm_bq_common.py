#!/usr/bin/env python3
"""Shared BigQuery CLI helpers for the SourceMedium analyst scripts.

Not a command. `sm_bq_doctor.py`, `sm_bq_discover.py`, and `sm_bq_query.py`
import it so warehouse resolution, dry-runs, and capped execution behave the
same way in every script.
"""

from __future__ import annotations

import json
import re
import subprocess

DEFAULT_MAX_BYTES_BILLED = 1_073_741_824  # 1 GiB
DEFAULT_MAX_ROWS = 1000

# The shared ("Foundation") lane keeps every tenant in one project with
# tenant-prefixed datasets; the dedicated ("Pro") lane gives a tenant its own
# project with unprefixed datasets. `sm_utils` is unprefixed on both.
SHARED_PROJECT = "sourcemedium-bi"
SM_DATASETS = ("sm_metadata", "sm_transformed_v2", "sm_views", "sm_experimental")


class BqError(RuntimeError):
    """A bq command failed; the message is bq's own output."""


def bq_base(project: str | None, location: str | None) -> list[str]:
    cmd = ["bq"]
    if project:
        cmd.append(f"--project_id={project}")
    if location:
        cmd.append(f"--location={location}")
    return cmd


def run(cmd: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def run_sql(cmd: list[str], sql: str) -> subprocess.CompletedProcess[str]:
    # SQL goes over stdin: as an argument, a query that opens with a `--`
    # comment is parsed by bq as a command-line flag.
    return run(cmd, stdin=sql)


def dry_run(project: str | None, location: str | None, sql: str) -> dict:
    """Dry-run `sql`. Returns bytes, statement type, and referenced tables as BigQuery reports them."""
    result = run_sql(bq_base(project, location) + ["query", "--use_legacy_sql=false", "--dry_run", "--format=json"], sql)
    if result.returncode != 0:
        raise BqError((result.stderr or result.stdout).strip())
    job = json.loads(result.stdout)
    stats = job.get("statistics", {})
    query = stats.get("query", {})
    return {
        "bytes_processed": int(stats.get("totalBytesProcessed", query.get("totalBytesProcessed", 0))),
        "bytes_accuracy": query.get("totalBytesProcessedAccuracy"),
        "statement_type": query.get("statementType"),
        "referenced_tables": [
            f"{t['projectId']}.{t['datasetId']}.{t['tableId']}" for t in query.get("referencedTables", [])
        ],
    }


def execute(
    project: str | None,
    location: str | None,
    sql: str,
    *,
    max_bytes_billed: int,
    max_rows: int,
) -> tuple[list[dict], bool]:
    """Run `sql` with a bytes cap. Returns (rows, truncated).

    bq returns 100 rows unless told otherwise, and says nothing when it stops
    there. Asking for one row more than the caller's limit is how truncation
    becomes visible instead of silent.
    """
    result = run_sql(
        bq_base(project, location)
        + [
            "query",
            "--use_legacy_sql=false",
            f"--maximum_bytes_billed={max_bytes_billed}",
            f"--max_rows={max_rows + 1}",
            "--format=json",
            "--quiet",
        ],
        sql,
    )
    if result.returncode != 0:
        raise BqError((result.stderr or result.stdout).strip())
    rows = json.loads(result.stdout) if result.stdout.strip() else []
    return rows[:max_rows], len(rows) > max_rows


def normalize_tenant(tenant: str) -> str:
    """The dataset prefix SourceMedium derives from a tenant id."""
    key = re.sub(r"[^a-z0-9]+", "", tenant.strip().lower())
    return f"_{key}" if key[:1].isdigit() else key


def list_datasets(project: str, location: str | None) -> list[str]:
    result = run(bq_base(project, location) + ["ls", "--format=json", "--max_results=10000"])
    if result.returncode != 0:
        raise BqError((result.stderr or result.stdout).strip())
    if not result.stdout.strip():
        return []
    return [d["datasetReference"]["datasetId"] for d in json.loads(result.stdout)]


def resolve_layout(
    project: str,
    location: str | None,
    *,
    tenant: str | None = None,
    metadata_dataset: str | None = None,
    transformed_dataset: str | None = None,
) -> dict:
    """Resolve which SourceMedium datasets this project holds.

    Explicit dataset flags win, then `--tenant`, then what the caller can see:
    a dataset listing returns only the datasets the caller can read, so on the
    shared project a customer sees their own prefix and nothing else.
    """
    if tenant:
        prefix, source = f"{normalize_tenant(tenant)}_", "--tenant"
    elif metadata_dataset or transformed_dataset:
        named = transformed_dataset or metadata_dataset or ""
        base = "sm_transformed_v2" if transformed_dataset else "sm_metadata"
        prefix = named[: -len(base)] if named.endswith(base) else ""
        source = "explicit dataset flags"
    else:
        visible = list_datasets(project, location)
        if "sm_transformed_v2" in visible:
            prefix, source = "", "dataset listing"
        else:
            prefixes = sorted({d[: -len("sm_transformed_v2")] for d in visible if d.endswith("_sm_transformed_v2")})
            if len(prefixes) != 1:
                found = ", ".join(p + "sm_transformed_v2" for p in prefixes) or "none"
                raise BqError(
                    f"Cannot tell which SourceMedium datasets to use in {project} "
                    f"(transformed datasets visible: {found}). Pass --tenant or "
                    "--metadata-dataset and --transformed-dataset."
                )
            prefix, source = prefixes[0], "dataset listing"

    datasets = {name: f"{prefix}{name}" for name in SM_DATASETS}
    if metadata_dataset:
        datasets["sm_metadata"] = metadata_dataset
    if transformed_dataset:
        datasets["sm_transformed_v2"] = transformed_dataset
    return {
        "project": project,
        "lane": "shared" if prefix or project == SHARED_PROJECT else "dedicated",
        "resolved_from": source,
        "datasets": datasets,
    }
