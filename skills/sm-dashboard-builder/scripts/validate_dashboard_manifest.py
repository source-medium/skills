#!/usr/bin/env python3
"""Validate a SourceMedium dashboard manifest before rendering or BI handoff."""

from __future__ import annotations

import argparse
from pathlib import Path

from dashboard_manifest import load_manifest, validate_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to dashboard manifest JSON")
    parser.add_argument("--strict", action="store_true", help="Require publish-ready metric/query QA metadata")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    errors, warnings = validate_manifest(manifest, strict=args.strict)
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Dashboard manifest is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
