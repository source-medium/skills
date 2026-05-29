#!/usr/bin/env python3
"""Shared validation helpers for SourceMedium dashboard manifests."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")
UNSAFE_SQL_RE = re.compile(
    r"\b(ALTER|CALL|CREATE|DELETE|DROP|EXPORT|GRANT|INSERT|MERGE|REVOKE|TRUNCATE|UPDATE)\b",
    re.IGNORECASE,
)
RATIO_TOKEN_RE = re.compile(r"(aov|cac|cpa|cpc|cpm|ctr|cvr|mer|rate|ratio|roas|share|percent|%)", re.IGNORECASE)


def safe_id(raw: str) -> str:
    value = SAFE_ID_RE.sub("-", raw.strip()).strip("-").lower()
    if not value:
        raise ValueError("Chart/table ids must contain at least one letter or number")
    return value


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")
    return manifest


def validate_manifest(manifest: dict[str, Any], *, strict: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    _validate_top_level(manifest, errors, warnings, strict=strict)
    contract_ids, ratio_contract_ids = _validate_metric_contracts(manifest, errors, warnings, strict=strict)

    seen_ids: set[str] = set()
    _validate_tiles(
        manifest.get("charts", []),
        "Chart",
        errors,
        warnings,
        seen_ids,
        contract_ids,
        ratio_contract_ids,
        strict=strict,
        require_vega_lite=True,
    )
    _validate_tiles(
        manifest.get("tables", []),
        "Table",
        errors,
        warnings,
        seen_ids,
        contract_ids,
        ratio_contract_ids,
        strict=strict,
        require_vega_lite=False,
    )

    return errors, warnings


def validate_manifest_or_raise(manifest: dict[str, Any], *, strict: bool = False) -> list[str]:
    errors, warnings = validate_manifest(manifest, strict=strict)
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise ValueError(f"Dashboard manifest validation failed:\n{details}")
    return warnings


def _validate_top_level(
    manifest: dict[str, Any],
    errors: list[str],
    warnings: list[str],
    *,
    strict: bool,
) -> None:
    title = manifest.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("Manifest requires a non-empty string title")

    charts = manifest.get("charts", [])
    if not isinstance(charts, list):
        errors.append("Manifest field charts must be a list")

    tables = manifest.get("tables", [])
    if not isinstance(tables, list):
        errors.append("Manifest field tables must be a list")

    if not charts and not tables:
        warnings.append("Manifest has no charts or tables")

    scope = manifest.get("scope")
    if strict and not isinstance(scope, dict):
        errors.append("Strict manifest requires scope object")
    elif isinstance(scope, dict):
        for field in ("project", "timeframe"):
            if not scope.get(field):
                warnings.append(f"Scope is missing {field}")

    freshness = manifest.get("freshness")
    if strict and not freshness:
        errors.append("Strict manifest requires freshness status")

    notes = manifest.get("notes", [])
    if notes and not isinstance(notes, list):
        errors.append("Manifest field notes must be a list")
    if strict and not notes:
        warnings.append("Strict manifest should include notes or QA caveats")


def _validate_metric_contracts(
    manifest: dict[str, Any],
    errors: list[str],
    warnings: list[str],
    *,
    strict: bool,
) -> tuple[set[str], set[str]]:
    raw_contracts = manifest.get("metric_contracts", [])
    if not isinstance(raw_contracts, list):
        errors.append("Manifest field metric_contracts must be a list when present")
        return set(), set()
    if strict and not raw_contracts:
        errors.append("Strict manifest requires metric_contracts")

    contract_ids: set[str] = set()
    ratio_contract_ids: set[str] = set()
    for index, contract in enumerate(raw_contracts, start=1):
        if not isinstance(contract, dict):
            errors.append(f"Metric contract {index} must be an object")
            continue
        contract_id = contract.get("id")
        if not isinstance(contract_id, str) or not contract_id.strip():
            errors.append(f"Metric contract {index} requires a non-empty id")
            continue
        normalized_id = safe_id(contract_id)
        if normalized_id in contract_ids:
            errors.append(f"Duplicate metric contract id after normalization: {contract_id}")
        contract_ids.add(normalized_id)

        for field in ("name", "formula", "grain", "date_field", "source_tables"):
            if strict and not contract.get(field):
                errors.append(f"Metric contract {contract_id} requires {field}")

        source_tables = contract.get("source_tables", [])
        if source_tables and not isinstance(source_tables, list):
            errors.append(f"Metric contract {contract_id} source_tables must be a list")

        additivity = str(contract.get("additivity", "")).lower()
        metric_type = str(contract.get("type", "")).lower()
        is_ratio = (
            additivity == "non_additive"
            or metric_type in {"ratio", "rate", "percentage"}
            or bool(RATIO_TOKEN_RE.search(f"{contract_id} {contract.get('name', '')}"))
        )
        if is_ratio:
            ratio_contract_ids.add(normalized_id)
            if strict and (not contract.get("numerator") or not contract.get("denominator")):
                errors.append(f"Ratio/rate metric contract {contract_id} requires numerator and denominator")

        if strict and additivity not in {"additive", "non_additive", "semi_additive"}:
            warnings.append(f"Metric contract {contract_id} should declare additivity")

    return contract_ids, ratio_contract_ids


def _validate_tiles(
    raw_tiles: Any,
    label: str,
    errors: list[str],
    warnings: list[str],
    seen_ids: set[str],
    contract_ids: set[str],
    ratio_contract_ids: set[str],
    *,
    strict: bool,
    require_vega_lite: bool,
) -> None:
    if not isinstance(raw_tiles, list):
        return
    for index, tile in enumerate(raw_tiles, start=1):
        if not isinstance(tile, dict):
            errors.append(f"{label} {index} must be an object")
            continue

        tile_id = tile.get("id")
        if not isinstance(tile_id, str) or not tile_id.strip():
            errors.append(f"{label} {index} requires a non-empty id")
            continue
        normalized_id = safe_id(tile_id)
        if normalized_id in seen_ids:
            errors.append(f"Duplicate tile id after normalization: {tile_id}")
        seen_ids.add(normalized_id)

        sql = tile.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            errors.append(f"{label} {tile_id} requires a SQL receipt")
        elif not _is_safe_select_sql(sql):
            errors.append(f"{label} {tile_id} SQL must be SELECT/WITH-only and non-mutating")

        rows = tile.get("data" if require_vega_lite else "rows", [])
        if require_vega_lite and not isinstance(rows, list):
            errors.append(f"{label} {tile_id} requires data as a list of rows")
        if not require_vega_lite and not isinstance(rows, list):
            errors.append(f"{label} {tile_id} rows must be a list")
        if strict and len(rows) == 0:
            errors.append(f"{label} {tile_id} has no rows in strict mode")
        elif len(rows) == 0:
            warnings.append(f"{label} {tile_id} has no rows")

        metric_ids = _normalize_id_list(tile.get("metric_contract_ids", []), f"{label} {tile_id}", errors)
        if strict and not metric_ids:
            errors.append(f"{label} {tile_id} requires metric_contract_ids in strict mode")
        unknown = metric_ids - contract_ids
        for metric_id in sorted(unknown):
            errors.append(f"{label} {tile_id} references unknown metric contract id: {metric_id}")

        source_tables = tile.get("source_tables", [])
        if source_tables and not isinstance(source_tables, list):
            errors.append(f"{label} {tile_id} source_tables must be a list")
        if strict and not source_tables:
            errors.append(f"{label} {tile_id} requires source_tables in strict mode")

        qa = tile.get("query_metadata", {})
        if qa and not isinstance(qa, dict):
            errors.append(f"{label} {tile_id} query_metadata must be an object")
            qa = {}
        if strict:
            _validate_query_metadata(qa, f"{label} {tile_id}", errors, warnings)

        if metric_ids & ratio_contract_ids or RATIO_TOKEN_RE.search(f"{tile_id} {tile.get('title', '')}"):
            denominator_check = qa.get("denominator_check") if isinstance(qa, dict) else None
            if strict and not denominator_check:
                errors.append(f"{label} {tile_id} requires denominator_check for ratio/rate metric")
            elif not denominator_check:
                warnings.append(f"{label} {tile_id} should include denominator_check for ratio/rate metric")

        if require_vega_lite:
            spec = tile.get("vega_lite")
            if not isinstance(spec, dict):
                errors.append(f"{label} {tile_id} requires a vega_lite object for the bundled HTML builder")
            else:
                _validate_vega_lite_fields(spec, rows, f"{label} {tile_id}", errors, warnings, strict=strict)


def _validate_query_metadata(
    qa: Any,
    label: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not isinstance(qa, dict) or not qa:
        errors.append(f"{label} requires query_metadata in strict mode")
        return
    for field in ("dry_run_bytes", "row_count", "freshness_checked_at"):
        if field not in qa:
            errors.append(f"{label} query_metadata requires {field}")
    if isinstance(qa.get("row_count"), int) and qa["row_count"] < 1:
        errors.append(f"{label} query_metadata row_count must be positive")
    if "dry_run_bytes" in qa and not isinstance(qa["dry_run_bytes"], int):
        errors.append(f"{label} query_metadata dry_run_bytes must be an integer")
    if "qa_status" in qa and qa["qa_status"] not in {"pass", "warn", "fail"}:
        warnings.append(f"{label} query_metadata qa_status should be pass, warn, or fail")


def _validate_vega_lite_fields(
    spec: dict[str, Any],
    rows: Any,
    label: str,
    errors: list[str],
    warnings: list[str],
    *,
    strict: bool,
) -> None:
    if "encoding" not in spec and "layer" not in spec and "hconcat" not in spec and "vconcat" not in spec:
        warnings.append(f"{label} has no encoding/layer/concat section")
    if not isinstance(rows, list) or not rows:
        return

    available_fields: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            available_fields.update(str(key) for key in row.keys())

    referenced_fields = _collect_spec_fields(spec)
    missing_fields = sorted(field for field in referenced_fields if field not in available_fields)
    for field in missing_fields:
        message = f"{label} Vega-Lite references field missing from data: {field}"
        if strict:
            errors.append(message)
        else:
            warnings.append(message)


def _collect_spec_fields(value: Any) -> set[str]:
    fields: set[str] = set()
    if isinstance(value, dict):
        raw_field = value.get("field")
        if isinstance(raw_field, str):
            fields.add(raw_field)
        for child in value.values():
            fields.update(_collect_spec_fields(child))
    elif isinstance(value, list):
        for child in value:
            fields.update(_collect_spec_fields(child))
    return fields


def _normalize_id_list(value: Any, label: str, errors: list[str]) -> set[str]:
    if value in (None, ""):
        return set()
    if not isinstance(value, list):
        errors.append(f"{label} metric_contract_ids must be a list")
        return set()
    normalized: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{label} metric_contract_ids values must be non-empty strings")
            continue
        normalized.add(safe_id(item))
    return normalized


def _is_safe_select_sql(sql: str) -> bool:
    stripped = _strip_sql_comments(sql).strip().rstrip(";").lstrip("(").strip()
    if ";" in stripped:
        return False
    if UNSAFE_SQL_RE.search(stripped):
        return False
    return bool(re.match(r"^(WITH|SELECT)\b", stripped, flags=re.IGNORECASE | re.DOTALL))


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--.*?$", " ", sql, flags=re.MULTILINE)
    return sql
