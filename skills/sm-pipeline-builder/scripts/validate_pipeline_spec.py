#!/usr/bin/env python3
"""Validate a bespoke pipeline spec file (YAML or JSON).

Checks that the spec declares everything an idempotent, operable pipeline
needs: source, destination, per-stream name, grain, primary key, load mode,
and — per mode — the cursor, overlap, restatement horizon, and window column
that make re-running a window safe. Also enforces the hard rules a spec can
violate on paper: never writing to SourceMedium `sm_*` datasets, never
carrying a credential value instead of a secret name, and declaring a
ceiling for the write side.

Warnings cover commonly skipped declarations (auth secret, auth failure mode,
bootstrap window, deletes behavior, timezone close, money scale, coverage
checks, cost ceiling); --strict promotes them to failures for go-live.

Exit 0 when valid, exit 2 with reasons when not. Malformed files exit 2 with
a message, never a traceback.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


LOAD_MODES = ("merge", "append_restate", "snapshot")
DESTINATION_KINDS = ("bigquery", "external")
OVERLAP_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*[smhdw]$", re.IGNORECASE)
DATE_HINT_RE = re.compile(r"date|day", re.IGNORECASE)

# Credential shapes that are unambiguous wherever they appear in a spec.
# The QA harness imports this to scan the package itself, so keep it the one
# definition of "this is a secret value, not a secret name".
CREDENTIAL_PATTERNS = (
    ("Shopify access token", re.compile(r"shp(at|ss|ca|pa)_[A-Za-z0-9]{16,}")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}")),
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("Stripe key", re.compile(r"\b[rsp]k_(live|test)_[A-Za-z0-9]{16,}")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}")),
    ("AWS access key id", re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("Google OAuth token", re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}")),
    ("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")),
    ("Authorization header value", re.compile(r"\bBearer\s+[A-Za-z0-9_.=-]{16,}")),
    ("SendGrid key", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)
# Applied only under credential-ish keys: a separator-free alphanumeric blob is
# a value, not a name. Secret NAMES carry separators (FOO_BAR, a/b/c, an ARN).
# `\bkey\b` deliberately does not match `primary_key` or `surrogate_key`, whose
# values are column names that may legitimately look opaque.
SECRETISH_KEY_RE = re.compile(r"secret|token|password|passwd|credential|api[_-]?key|\bkey\b", re.IGNORECASE)
OPAQUE_BLOB_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9+/=]{20,}$")


class Report:
    """Collects findings. Callers say what they found; --strict decides what fails."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_spec(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read spec file: {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
            raise SystemExit(2)
    else:
        try:
            import yaml
        except ImportError:
            print(f"error: {path} looks like YAML but PyYAML is not installed", file=sys.stderr)
            print("hint: pip install pyyaml, or convert the spec to JSON", file=sys.stderr)
            raise SystemExit(2)
        try:
            data = yaml.safe_load(text)
        except Exception as exc:
            print(f"error: {path} is not valid YAML: {exc}", file=sys.stderr)
            raise SystemExit(2)
    if not isinstance(data, dict):
        print(f"error: {path} must contain a top-level mapping", file=sys.stderr)
        raise SystemExit(2)
    return data


# --- shape helpers ---------------------------------------------------------
# A spec is hand-written YAML, so any field can arrive as the wrong type. These
# turn "wrong type" into a reported error instead of an exception, so that no
# malformed spec can reach a `.get()` or an iteration on a non-container.


def get_mapping(parent: dict, key: str, where: str, report: Report) -> dict:
    """Return parent[key] as a mapping; report and return {} when malformed."""
    value = parent.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        report.error(f"{where}: `{key}` must be a mapping, got {type(value).__name__}")
        return {}
    return value


def get_sequence(parent: dict, key: str, where: str, report: Report) -> list:
    """Return parent[key] as a list; report and return [] when malformed."""
    value = parent.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        report.error(f"{where}: `{key}` must be a list, got {type(value).__name__}")
        return []
    return value


def column_list(value: object) -> list[str] | None:
    """Return value when it is a non-empty list of column names, else None."""
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return value
    return None


# --- checks ----------------------------------------------------------------


def scan_for_credentials(node: object, path: str, report: Report) -> None:
    """Walk the spec and flag credential VALUES. Specs name secrets, never hold them."""
    if isinstance(node, dict):
        for key, value in node.items():
            scan_for_credentials(value, f"{path}.{key}" if path else str(key), report)
        return
    if isinstance(node, list):
        for index, value in enumerate(node):
            scan_for_credentials(value, f"{path}[{index}]", report)
        return
    if not isinstance(node, str):
        return
    for label, pattern in CREDENTIAL_PATTERNS:
        if pattern.search(node):
            report.error(
                f"`{path}` looks like a live {label}: specs name secrets, never carry them — "
                "put the value in a secret manager and reference it by name, then rotate this one"
            )
            return
    leaf = path.rsplit(".", 1)[-1]
    if SECRETISH_KEY_RE.search(leaf) and OPAQUE_BLOB_RE.match(node.strip()):
        report.error(
            f"`{path}` looks like a credential value, not a secret name: specs name secrets, "
            "never carry them — reference the secret by name and rotate this value"
        )


def validate_source(spec: dict, report: Report) -> None:
    source = spec.get("source")
    if not isinstance(source, dict) or not source.get("name"):
        report.error("`source.name` is required")
        return
    pagination = get_mapping(source, "pagination", "`source`", report)
    if not pagination.get("stop_condition"):
        report.warn("`source.pagination.stop_condition` undeclared: prove the page-walk stop with a live probe")
    if not source.get("rate_limit"):
        report.warn("`source.rate_limit` undeclared: record the limit model (rps / daily budget) and value")
    if not source.get("auth_secret"):
        report.warn("`source.auth_secret` undeclared: name the secret the runtime resolves (never its value)")
    if not source.get("auth_failure_mode"):
        report.warn("`source.auth_failure_mode` undeclared: state what fails on expiry and who re-authenticates")


def validate_destination(spec: dict, report: Report) -> None:
    destination = spec.get("destination")
    if not isinstance(destination, dict):
        report.error("`destination` is required and must be a mapping")
        return

    kind = destination.get("kind", "bigquery")
    if kind not in DESTINATION_KINDS:
        report.error(f"`destination.kind` must be one of {', '.join(DESTINATION_KINDS)} (default bigquery)")
        kind = "bigquery"

    if kind == "bigquery":
        if not destination.get("project"):
            report.error("`destination.project` is required for a BigQuery destination")
        if not destination.get("dataset_raw"):
            report.warn("`destination.dataset_raw` undeclared: name the immutable landing dataset")
    else:
        if not destination.get("system"):
            report.error(
                "`destination.system` is required for an external destination "
                "(name the system and environment you are writing into)"
            )
        if not destination.get("pii"):
            report.error(
                "`destination.pii` is required for an external destination: list the PII columns "
                "leaving the warehouse, or `none` — egress without a declared PII scope is not reviewable"
            )

    # Hard rule: bespoke pipelines read `sm_*` and write their own datasets.
    for field, value in destination.items():
        if not str(field).startswith("dataset") or not isinstance(value, str):
            continue
        if value.strip().lower().startswith("sm_"):
            report.error(
                f"`destination.{field}` is `{value}`: never write to SourceMedium `sm_*` datasets — "
                "they are rebuilt by SourceMedium jobs and your writes will be overwritten. "
                "Land bespoke tables in a customer-owned dataset"
            )


def validate_stream(index: int, stream: object, seen_names: set[str], report: Report) -> None:
    where = f"streams[{index}]"
    if not isinstance(stream, dict):
        report.error(f"{where} must be a mapping, got {type(stream).__name__}")
        return

    name = stream.get("name")
    if not isinstance(name, str) or not name:
        report.error(f"{where}: `name` is required (state is keyed per pipeline, stream)")
        name = f"index {index}"
    elif name in seen_names:
        report.error(f"stream `{name}`: duplicate stream name (state is keyed per pipeline, stream)")
    else:
        seen_names.add(name)
    where = f"stream `{name}`"

    grain = column_list(stream.get("grain"))
    if grain is None:
        report.error(f"{where}: `grain` must be a non-empty list of column names")
    keys = column_list(stream.get("primary_key"))
    if keys is None:
        report.error(f"{where}: `primary_key` must be a non-empty list of column names")

    validate_key_derivation(stream, grain, keys, where, report)

    load = get_mapping(stream, "load", where, report)
    mode = load.get("mode")
    if mode not in LOAD_MODES:
        report.error(f"{where}: `load.mode` must be one of {', '.join(LOAD_MODES)}")
        mode = None

    incremental = get_mapping(stream, "incremental", where, report)
    if mode == "merge":
        validate_merge(incremental, where, report)
    elif mode == "append_restate":
        validate_append_restate(stream, incremental, where, report)

    validate_money(stream, where, report)
    validate_declarations(stream, grain, where, report)


def validate_key_derivation(
    stream: dict, grain: list[str] | None, keys: list[str] | None, where: str, report: Report
) -> None:
    """The primary key must come from the grain, directly or through a declared surrogate."""
    if grain is None or keys is None:
        return
    surrogate_name = validate_surrogate_key(stream, grain, keys, where, report)
    undeclared = [key for key in keys if key not in grain and key != surrogate_name]
    if undeclared:
        report.error(
            f"{where}: `primary_key` columns not derivable from `grain`: {', '.join(undeclared)} — "
            "add them to the grain, or declare a `surrogate_key` with `name` and `from` "
            "(required anyway when any grain column is nullable: NULL keys never MERGE)"
        )


def validate_surrogate_key(
    stream: dict, grain: list[str], keys: list[str], where: str, report: Report
) -> str | None:
    """Validate an optional `surrogate_key` block; return the surrogate column name."""
    if "surrogate_key" not in stream:
        return None
    surrogate = get_mapping(stream, "surrogate_key", where, report)
    if not surrogate:
        return None

    name = surrogate.get("name")
    if not isinstance(name, str) or not name:
        report.error(f"{where}: `surrogate_key.name` is required (the hashed column added to the table)")
        name = None
    elif name not in keys:
        report.error(
            f"{where}: `surrogate_key.name` `{name}` is not in `primary_key` — "
            "declare the surrogate as the merge key it is meant to be"
        )

    sources = column_list(surrogate.get("from"))
    if sources is None:
        report.error(f"{where}: `surrogate_key.from` must be a non-empty list of grain columns to hash")
    else:
        outside = [column for column in sources if column not in grain]
        if outside:
            report.error(
                f"{where}: `surrogate_key.from` columns not in `grain`: {', '.join(outside)} — "
                "hash the declared grain so the key moves when the grain moves"
            )
    return name


def validate_merge(incremental: dict, where: str, report: Report) -> None:
    if not incremental.get("cursor_field"):
        report.error(f"{where}: merge mode requires `incremental.cursor_field` (updated time, not event time)")
    overlap = incremental.get("overlap")
    if not overlap:
        report.error(f"{where}: merge mode requires `incremental.overlap` (e.g. 48h)")
        return
    match = OVERLAP_RE.match(str(overlap))
    if not match:
        report.error(f"{where}: `incremental.overlap` {overlap!r} must look like 30m, 48h, 7d")
    elif float(match.group(1)) <= 0:
        report.error(f"{where}: `incremental.overlap` {overlap!r} must be greater than zero")


def validate_append_restate(stream: dict, incremental: dict, where: str, report: Report) -> None:
    restated = stream.get("restatement_days")
    if not isinstance(restated, (int, float)) or isinstance(restated, bool) or restated <= 0:
        report.error(f"{where}: append_restate mode requires positive `restatement_days`")
    if not incremental.get("window_column"):
        report.error(
            f"{where}: append_restate mode requires `incremental.window_column` — the column the "
            "window DELETE targets. The fetch window and the delete window must be the same window, "
            "and that is only checkable when the column is named"
        )


def validate_money(stream: dict, where: str, report: Report) -> None:
    for index, money in enumerate(get_sequence(stream, "money_fields", where, report)):
        mwhere = f"{where} money_fields[{index}]"
        if not isinstance(money, dict) or not money.get("name"):
            report.error(f"{mwhere}: money field needs a `name`")
            continue
        if not money.get("unit"):
            report.error(f"{where} money `{money['name']}`: `unit` is required (e.g. micro_cents, decimal_dollars)")
        if money.get("scale") is None:
            report.warn(
                f"{where} money `{money['name']}`: `scale` undeclared (NUMERIC scale to quantize to; "
                "0 is valid for zero-decimal currencies)"
            )


def validate_declarations(stream: dict, grain: list[str] | None, where: str, report: Report) -> None:
    if not stream.get("bootstrap_window"):
        report.warn(f"{where}: no `bootstrap_window` declared (bounded first-build window, never all history)")
    if not stream.get("deletes"):
        report.warn(f"{where}: no `deletes` declared (tombstone/status flag, or invisible hard-deletes)")
    looks_dated = any(
        DATE_HINT_RE.search(str(stream.get(field, ""))) for field in ("partition", "name")
    ) or any(DATE_HINT_RE.search(column) for column in (grain or []))
    if looks_dated and not stream.get("business_date_close"):
        report.warn(f"{where}: date-grained but no `business_date_close`: declare the source-local close")
    if not stream.get("coverage_check"):
        report.warn(f"{where}: no `coverage_check` declared (row-count floor or business-date coverage)")


def validate(spec: dict) -> tuple[list[str], list[str]]:
    report = Report()

    scan_for_credentials(spec, "", report)

    if not spec.get("pipeline"):
        report.error("top-level `pipeline` name is required")
    validate_source(spec, report)
    validate_destination(spec, report)
    if not spec.get("cost"):
        report.warn(
            "top-level `cost` block undeclared: bound the write side (max windows per backfill run, "
            "bytes/cost budget). A read-side bytes cap does not stop a backfill loop from spending"
        )

    streams = spec.get("streams")
    if not isinstance(streams, list) or not streams:
        report.error("`streams` must be a non-empty list")
        streams = []
    seen_names: set[str] = set()
    for index, stream in enumerate(streams):
        validate_stream(index, stream, seen_names, report)

    return report.errors, report.warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", help="Pipeline spec file (YAML or JSON)")
    parser.add_argument("--strict", action="store_true", help="Promote warnings to failures")
    args = parser.parse_args()

    path = Path(args.spec)
    if not path.exists():
        print(f"error: spec file not found: {path}", file=sys.stderr)
        return 2
    spec = load_spec(path)
    try:
        errors, warnings = validate(spec)
    except Exception as exc:
        # Every known malformed shape is reported by the helpers above; the QA
        # harness fuzzes the spec tree to keep it that way. Reaching here means
        # a validator bug, not a spec problem, so say so rather than blaming
        # the file — and still exit 2 so no caller mistakes it for success.
        print(f"internal error: validator bug on {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("hint: this is a bug in validate_pipeline_spec.py; please report the spec shape", file=sys.stderr)
        return 2

    for message in errors:
        print(f"error: {message}")
    for message in warnings:
        print(f"warning: {message}")

    failures = errors + (warnings if args.strict else [])
    if failures:
        print(f"invalid: {len(errors)} error(s), {len(warnings)} warning(s) in {path}")
        return 2
    if warnings:
        print(f"valid with {len(warnings)} warning(s): {path} (use --strict before go-live)")
    else:
        print(f"valid: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
