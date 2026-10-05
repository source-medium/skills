#!/usr/bin/env python3
"""Verify local CLI, auth, project, and SourceMedium BigQuery access.

Also resolves the warehouse layout: which lane the project is on and the
exact dataset names to use in SQL. Use the names it prints, not the defaults.
"""

from __future__ import annotations

import argparse
import json
import shutil

from sm_bq_common import BqError, dry_run, resolve_layout, run

EXIT_MISSING_TOOL = 2
EXIT_AUTH_OR_PROJECT = 3
EXIT_BIGQUERY = 4
EXIT_SOURCEMEDIUM_ACCESS = 5


def check_command(name: str, cmd: list[str]) -> dict[str, object]:
    if not shutil.which(cmd[0]):
        return {"name": name, "ok": False, "detail": f"{cmd[0]} not found on PATH"}
    result = run(cmd)
    output = (result.stdout or result.stderr).strip().splitlines()
    return {"name": name, "ok": result.returncode == 0, "detail": output[0] if output else ""}


def dry_run_check(project: str, location: str | None, sql: str, name: str, *, required: bool = True) -> dict[str, object]:
    try:
        estimate = dry_run(project, location, sql)
    except BqError as exc:
        return {"name": name, "ok": False, "required": required, "detail": str(exc).splitlines()[-1]}
    return {"name": name, "ok": True, "required": required, "detail": f"dry-run ok, {estimate['bytes_processed']} bytes"}


def finish(args: argparse.Namespace, payload: dict, code: int) -> int:
    if args.json:
        print(json.dumps(payload, indent=2))
        return code
    print("# SourceMedium BigQuery Doctor\n")
    for check in payload["checks"]:
        status = "PASS" if check["ok"] else ("WARN" if check.get("required") is False else "FAIL")
        print(f"- **{status}** {check['name']}: {check['detail']}")
    layout = payload.get("layout")
    if layout:
        print(f"\nProject: `{layout['project']}` ({layout['lane']} lane, resolved from {layout['resolved_from']})")
        print("Use these dataset names in SQL:")
        for name, dataset in layout["datasets"].items():
            print(f"- `<{name}>` = `{layout['project']}.{dataset}`")
        print(f"- `sm_utils` = `{layout['project']}.sm_utils`")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", help="Warehouse project, such as sm-acme or sourcemedium-bi.")
    parser.add_argument("--tenant", help="Shared-lane tenant id; datasets become <tenant>_sm_*.")
    parser.add_argument("--metadata-dataset", help="Metadata dataset. Default: resolved from the project.")
    parser.add_argument("--transformed-dataset", help="Transformed dataset. Default: resolved from the project.")
    parser.add_argument("--location", help="BigQuery location, such as US.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    checks: list[dict[str, object]] = [
        check_command("gcloud CLI", ["gcloud", "--version"]),
        check_command("bq CLI", ["bq", "version"]),
    ]
    if not all(check["ok"] for check in checks):
        return finish(args, {"checks": checks}, EXIT_MISSING_TOOL)

    auth = run(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"])
    active_account = auth.stdout.strip()
    checks.append({"name": "active gcloud account", "ok": auth.returncode == 0 and bool(active_account), "detail": active_account})

    configured = run(["gcloud", "config", "get-value", "project"]).stdout.strip()
    project = args.project or configured
    checks.append({"name": "project", "ok": bool(project), "detail": project or "no project configured; pass --project"})
    if args.project and configured and configured != args.project:
        checks.append(
            {
                "name": "gcloud default project",
                "ok": False,
                "required": False,
                "detail": f"gcloud is set to {configured}; scripts and SQL here use {args.project}",
            }
        )
    if not active_account or not project:
        return finish(args, {"checks": checks}, EXIT_AUTH_OR_PROJECT)

    checks.append(dry_run_check(project, args.location, "SELECT 1 AS ok", "BigQuery query jobs"))
    if not checks[-1]["ok"]:
        return finish(args, {"project": project, "checks": checks}, EXIT_BIGQUERY)

    try:
        layout = resolve_layout(
            project,
            args.location,
            tenant=args.tenant,
            metadata_dataset=args.metadata_dataset,
            transformed_dataset=args.transformed_dataset,
        )
    except BqError as exc:
        checks.append({"name": "SourceMedium datasets", "ok": False, "detail": str(exc)})
        return finish(args, {"project": project, "checks": checks}, EXIT_SOURCEMEDIUM_ACCESS)
    checks.append({"name": "SourceMedium datasets", "ok": True, "detail": f"{layout['lane']} lane"})

    ds = layout["datasets"]
    checks.append(
        dry_run_check(
            project,
            args.location,
            f"SELECT table_name FROM `{project}.{ds['sm_metadata']}.dim_data_dictionary` LIMIT 1",
            "metadata access",
        )
    )
    checks.append(
        dry_run_check(
            project,
            args.location,
            f"SELECT 1 FROM `{project}.{ds['sm_transformed_v2']}.obt_orders` LIMIT 1",
            "transformed table access",
        )
    )
    checks.append(
        dry_run_check(
            project,
            args.location,
            f"SELECT 1 FROM `{project}.sm_utils.dim_dates` LIMIT 1",
            "sm_utils access",
            required=False,
        )
    )

    code = 0 if all(c["ok"] for c in checks if c.get("required", True)) else EXIT_SOURCEMEDIUM_ACCESS
    return finish(args, {"project": project, "layout": layout, "checks": checks}, code)


if __name__ == "__main__":
    raise SystemExit(main())
