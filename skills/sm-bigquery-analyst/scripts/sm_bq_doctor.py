#!/usr/bin/env python3
"""Verify local CLI, auth, project, and SourceMedium BigQuery access."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys


EXIT_MISSING_TOOL = 2
EXIT_AUTH_OR_PROJECT = 3
EXIT_BIGQUERY = 4
EXIT_SOURCEMEDIUM_ACCESS = 5


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def bq_base(project: str | None, location: str | None) -> list[str]:
    cmd = ["bq"]
    if project:
        cmd.append(f"--project_id={project}")
    if location:
        cmd.append(f"--location={location}")
    return cmd


def check_command(name: str, cmd: list[str]) -> dict[str, object]:
    if not shutil.which(cmd[0]):
        return {"name": name, "ok": False, "detail": f"{cmd[0]} not found on PATH"}
    result = run(cmd)
    output = (result.stdout or result.stderr).strip().splitlines()
    return {
        "name": name,
        "ok": result.returncode == 0,
        "detail": output[0] if output else "",
    }


def dry_run(project: str | None, location: str | None, sql: str, name: str) -> dict[str, object]:
    result = run(bq_base(project, location) + ["query", "--use_legacy_sql=false", "--dry_run", sql])
    output = (result.stdout + result.stderr).strip()
    return {"name": name, "ok": result.returncode == 0, "detail": output}


def print_markdown(checks: list[dict[str, object]]) -> None:
    print("# SourceMedium BigQuery Doctor\n")
    for check in checks:
        status = "PASS" if check["ok"] else "FAIL"
        print(f"- **{status}** {check['name']}: {check['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Expected SourceMedium project ID, such as sm-acme.")
    parser.add_argument("--metadata-dataset", default="sm_metadata", help="Metadata dataset. Default: sm_metadata.")
    parser.add_argument(
        "--transformed-dataset",
        default="sm_transformed_v2",
        help="Transformed analytics dataset. Default: sm_transformed_v2.",
    )
    parser.add_argument("--location", help="BigQuery location, such as US.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    checks: list[dict[str, object]] = []
    checks.append(check_command("gcloud CLI", ["gcloud", "--version"]))
    checks.append(check_command("bq CLI", ["bq", "version"]))

    if not checks[0]["ok"] or not checks[1]["ok"]:
        if args.json:
            print(json.dumps({"checks": checks}, indent=2))
        else:
            print_markdown(checks)
        return EXIT_MISSING_TOOL

    auth = run(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"])
    active_account = auth.stdout.strip()
    checks.append({"name": "active gcloud account", "ok": auth.returncode == 0 and bool(active_account), "detail": active_account})

    configured_project = run(["gcloud", "config", "get-value", "project"])
    active_project = args.project or configured_project.stdout.strip()
    checks.append(
        {
            "name": "active project",
            "ok": bool(active_project),
            "detail": active_project or "no project configured; pass --project",
        }
    )
    checks.append(
        {
            "name": "SourceMedium project naming",
            "ok": bool(active_project)
            and (
                active_project.startswith("sm-")
                or args.metadata_dataset != "sm_metadata"
                or args.transformed_dataset != "sm_transformed_v2"
            ),
            "detail": (
                "expected a tenant project like sm-acme; for shared warehouses pass "
                "--metadata-dataset and --transformed-dataset"
            ),
        }
    )

    if not active_account or not active_project:
        if args.json:
            print(json.dumps({"checks": checks}, indent=2))
        else:
            print_markdown(checks)
        return EXIT_AUTH_OR_PROJECT

    checks.append(dry_run(active_project, args.location, "SELECT 1 AS ok", "BigQuery query jobs"))
    if not checks[-1]["ok"]:
        if args.json:
            print(json.dumps({"project": active_project, "checks": checks}, indent=2))
        else:
            print_markdown(checks)
        return EXIT_BIGQUERY

    checks.append(
        dry_run(
            active_project,
            args.location,
            f"SELECT table_name FROM `{active_project}.{args.metadata_dataset}.dim_data_dictionary` LIMIT 1",
            "SourceMedium metadata access",
        )
    )
    checks.append(
        dry_run(
            active_project,
            args.location,
            f"SELECT 1 FROM `{active_project}.{args.transformed_dataset}.obt_orders` LIMIT 1",
            "SourceMedium transformed table access",
        )
    )

    if args.json:
        print(json.dumps({"project": active_project, "checks": checks}, indent=2))
    else:
        print_markdown(checks)

    return 0 if all(check["ok"] for check in checks) else EXIT_SOURCEMEDIUM_ACCESS


if __name__ == "__main__":
    raise SystemExit(main())
