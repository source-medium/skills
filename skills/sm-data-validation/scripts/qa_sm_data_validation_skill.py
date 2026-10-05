#!/usr/bin/env python3
"""QA harness for the SourceMedium Data Validation skill package."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "assets" / "fixtures"
RECONCILE = SCRIPTS / "sm_reconcile_orders.py"


def run(
    name: str,
    cmd: list[str],
    expect: int = 0,
    require_text: tuple[str, ...] = (),
    forbid_text: tuple[str, ...] = (),
    forbid_traceback: bool = True,
) -> bool:
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    output = result.stdout + result.stderr
    ok = result.returncode == expect
    detail = ""
    if ok and forbid_traceback and "Traceback" in output:
        ok, detail = False, "output contained a traceback"
    for text in require_text:
        if ok and text not in output:
            ok, detail = False, f"expected text not found: {text!r}"
    for text in forbid_text:
        if ok and text in output:
            ok, detail = False, f"forbidden text present: {text!r}"
    print(f"{'PASS' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"  command: {' '.join(cmd)}")
        print(f"  expected exit: {expect}; actual: {result.returncode}")
        if detail:
            print(f"  reason: {detail}")
        if result.stdout.strip():
            print(f"  stdout: {result.stdout.strip()[:1500]}")
        if result.stderr.strip():
            print(f"  stderr: {result.stderr.strip()[:1500]}")
    return ok


def check(name: str, passed: bool, detail: str = "") -> bool:
    print(f"{'PASS' if passed else 'FAIL'} {name}")
    if not passed and detail:
        print(f"  {detail}")
    return passed


def validate_skill_md() -> bool:
    path = ROOT / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    frontmatter = text.split("---", 2)[1] if "---" in text else ""
    checks = [
        ("SKILL.md exists", path.exists()),
        ("frontmatter exists", bool(match)),
        ("name matches directory", "name: sm-data-validation" in text),
        ("description mentions SourceMedium", "SourceMedium" in frontmatter),
        ("description routes away from analysis", "sm-bigquery-analyst" in frontmatter),
        ("description routes away from dashboards", "sm-dashboard-builder" in frontmatter),
        ("description routes away from pipelines", "sm-pipeline-builder" in frontmatter),
        ("body names all three acquisition vectors", all(v in text for v in ("Vector 1", "Vector 2", "Vector 3"))),
        ("body references the comparator", "scripts/sm_reconcile_orders.py" in text),
        ("body references the QA harness", "scripts/qa_sm_data_validation_skill.py" in text),
        ("body references the manual export", "assets/MANUAL_SHOPIFY_EXPORT.md" in text),
        ("body references the readiness checklist", "assets/READINESS_CHECKLIST.md" in text),
        ("body opens with Before you start ahead of Workflow", 0 < text.find("## Before you start") < text.find("## Workflow")),
        ("Before you start names the BigQuery roles", "roles/bigquery.jobUser" in text and "roles/bigquery.dataViewer" in text),
        ("Before you start says what is never requested", "### Never requested" in text),
        ("body requires window padding", "pad" in text.lower()),
        ("body forbids credentials", "credential" in text.lower()),
    ]
    ok = True
    for name, passed in checks:
        ok = check(name, passed) and ok
    return ok


def validate_reference_routing() -> bool:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    on_disk = {path.name for path in (ROOT / "references").glob("*.md")}
    routed = set(re.findall(r"references/([A-Za-z0-9_]+\.md)", text))
    ok = check("every reference file is routed from SKILL.md", on_disk <= routed, f"orphaned: {sorted(on_disk - routed)}")
    ok = check("every routed reference file exists", routed <= on_disk, f"dangling: {sorted(routed - on_disk)}") and ok

    dangling: list[str] = []
    pattern = r"(?<![\w/.-])(?:assets|scripts|evals|references)/[A-Za-z0-9_./-]+"
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir() or path.suffix not in (".md", ".yaml", ".json"):
            continue
        for ref in re.findall(pattern, path.read_text(encoding="utf-8")):
            target = ref.rstrip(".,;:)`")
            if target.endswith("/"):
                target = target[:-1]
            if not (ROOT / target).exists():
                dangling.append(f"{path.relative_to(ROOT)} -> {target}")
    return check("no dangling asset/script/reference paths", not dangling, "; ".join(dangling)) and ok


def validate_no_secrets() -> bool:
    """The package carries no credential values and no customer PII columns in fixtures."""
    patterns = [
        ("shopify token", re.compile(r"shp(at|ca|pa|ss)_[A-Za-z0-9]{16,}")),
        ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.")),
        ("aws key", re.compile(r"AKIA[0-9A-Z]{16}")),
        ("google api key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
        ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ]
    hits: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts or path == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in patterns:
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT)} ({label})")
                break
    ok = check("no credential values in package", not hits, f"found in: {hits}")

    email_hits: list[str] = []
    for path in sorted(FIXTURES.glob("*.csv")):
        if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", path.read_text(encoding="utf-8")):
            email_hits.append(path.name)
    return check("fixtures carry no email addresses", not email_hits, f"found in: {email_hits}") and ok


def validate_json_files() -> bool:
    ok = True
    for path in [ROOT / "evals" / "evals.json"]:
        try:
            json.loads(path.read_text(encoding="utf-8"))
            print(f"PASS valid JSON: {path.relative_to(ROOT)}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL valid JSON: {path.relative_to(ROOT)}: {exc}")
            ok = False
    return ok


def validate_evals() -> bool:
    data = json.loads((ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
    examples = data.get("examples", [])
    triggers = [e for e in examples if e.get("should_trigger")]
    negatives = [e for e in examples if not e.get("should_trigger")]
    ok = check("evals have trigger cases", len(triggers) >= 3, f"got {len(triggers)}")
    ok = check("evals have negative cases", len(negatives) >= 3, f"got {len(negatives)}") and ok
    shaped = all(
        isinstance(e.get("prompt"), str) and isinstance(e.get("expectations"), list) and e["expectations"]
        for e in examples
    )
    return check("every eval has a prompt and expectations", shaped) and ok


def validate_shopifyql_assets() -> bool:
    ok = True
    for path in sorted((ROOT / "assets" / "shopifyql").glob("*.shopifyql")):
        text = path.read_text(encoding="utf-8")
        ok = check(f"{path.name} starts with FROM sales", text.lstrip().startswith("FROM sales")) and ok
        ok = check(f"{path.name} carries both window placeholders", "{{start_minus_1}}" in text and "{{end_plus_1}}" in text) and ok
    return ok


def comparator_cases() -> bool:
    ok = True
    py = sys.executable
    ok &= run("comparator --help", [py, str(RECONCILE), "--help"])

    ok &= run(
        "clean pair reconciles (exit 0)",
        [py, str(RECONCILE), "--shopify", str(FIXTURES / "clean_shopify_sales_by_order.csv"),
         "--sm", str(FIXTURES / "clean_sm_orders.csv"), "--window", "2026-08-01", "2026-08-02"],
        expect=0,
        require_text=("**Verdict:** `reconciled`", "| Orders | 4 | 4 | +0 |"),
        forbid_text=("WARNING",),
    )
    ok &= run(
        "clean pair: totals row and padded days excluded from totals",
        [py, str(RECONCILE), "--shopify", str(FIXTURES / "clean_shopify_sales_by_order.csv"),
         "--sm", str(FIXTURES / "clean_sm_orders.csv"), "--window", "2026-08-01", "2026-08-02"],
        expect=0,
        require_text=("| net | 570.50 | 570.50 | 0.00 |", "2026-07-31 (outside window)"),
    )

    planted = [py, str(RECONCILE), "--shopify", str(FIXTURES / "planted_shopify_sales_by_order.csv"),
               "--sm", str(FIXTURES / "planted_sm_orders.csv"), "--window", "2026-08-01", "2026-08-02"]
    with tempfile.TemporaryDirectory() as tempdir:
        ok &= run(
            "planted pair classifies every planted cause, all orders compared (exit 1)",
            planted + ["--out-dir", tempdir],
            expect=1,
            require_text=(
                "| Orders | 6 | 3 | -3 |",              # return-only row is not an order
                "`match` | 1 | 0.00",                   # #1005: POS on Shopify, retail in SM, compared like any order
                "`refund-attribution` | 1 | 20.00",     # #1002: SM has no refund yet
                "`day-shift` | 1 | -225.00",            # #1003: Shopify 08-02, SM local 08-03
                "`prior-period-return` | 1 | 30.00",    # #0990: refund of an order sold before the window
                "`sm-invalid` | 1 | -45.50",            # #1004: cancelled, SM invalid
                "`sm-channel` | 1 | -60.00",            # #1006: SM draft_orders
                "`missing-in-sm` | 1 | -99.00",         # #1008: no SM row
                "`unexplained-sm-only` | 1 | 42.00",    # #1007: valid SM order Shopify lacks
                "Headline net delta (SM - Shopify): **-337.50**",
                "residual (unexplained classes): **-57.00** across 2 orders",
            ),
            forbid_text=("WARNING", "| `channel-basis` |"),
        )
        for name in ("matched_deltas.csv", "shopify_only.csv", "sm_only.csv", "attribution.csv"):
            ok = check(f"out-dir writes {name}", (Path(tempdir) / name).exists()) and ok

    ok &= run(
        "planted pair with Shopify offset collapses day-shift",
        planted + ["--shopify-utc-offset", "-7"],
        expect=1,
        require_text=("`match` | 2 | 0.00",),
        forbid_text=("| `day-shift` |",),
    )
    ok &= run(
        "planted pair under --basis exclude-pos sets the POS order aside with its effect",
        planted + ["--basis", "exclude-pos"],
        expect=1,
        require_text=("`channel-basis` | 1 | -270.00",),
        forbid_text=("| `match` |",),
    )
    ok &= run(
        "orders-page export is detected, collapsed per order, POS compared like any order",
        [py, str(RECONCILE), "--shopify", str(FIXTURES / "planted_shopify_orders_export.csv"),
         "--sm", str(FIXTURES / "planted_sm_orders.csv"), "--window", "2026-08-01", "2026-08-02"],
        expect=1,
        require_text=(
            "Shopify export format: `orders_export`",
            "Orders-page export detected",
            "`match` | 2 | 0.00",              # #1005 (pos) and #1007 (two line rows, 2 x 21.00)
            "`refund-attribution` | 1 | 20.00",
            "`sm-invalid` | 1 | -45.50",
        ),
        forbid_text=("| `missing-in-sm` |", "| `channel-basis` |"),
    )

    with tempfile.TemporaryDirectory() as tempdir:
        bad = Path(tempdir) / "bad.csv"
        bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
        ok &= run(
            "unrecognized Shopify export exits 2 with a message",
            [py, str(RECONCILE), "--shopify", str(bad), "--sm", str(FIXTURES / "clean_sm_orders.csv")],
            expect=2,
            require_text=("unrecognized Shopify export",),
        )
        dup = Path(tempdir) / "dup.csv"
        dup.write_text(
            "order_id,order_name,sm_channel,is_order_sm_valid,order_processed_at,order_processed_at_local_datetime,order_net_revenue\n"
            "1,#1,online_dtc,true,2026-08-01 00:00:00 UTC,2026-08-01T00:00:00,10\n"
            "1,#1,online_dtc,true,2026-08-01 00:00:00 UTC,2026-08-01T00:00:00,10\n",
            encoding="utf-8",
        )
        ok &= run(
            "duplicate SM order id exits 2",
            [py, str(RECONCILE), "--shopify", str(FIXTURES / "clean_shopify_sales_by_order.csv"), "--sm", str(dup)],
            expect=2,
            require_text=("duplicate order id",),
        )
        ok &= run(
            "missing file exits 2 without traceback",
            [py, str(RECONCILE), "--shopify", str(Path(tempdir) / "nope.csv"), "--sm", str(FIXTURES / "clean_sm_orders.csv")],
            expect=2,
        )
    return ok


def main() -> int:
    checks: list[bool] = []
    checks.append(validate_skill_md())
    checks.append(validate_reference_routing())
    checks.append(validate_no_secrets())
    checks.append(validate_json_files())
    checks.append(validate_evals())
    checks.append(validate_shopifyql_assets())
    checks.append(run("scripts compile", [sys.executable, "-m", "py_compile", *map(str, SCRIPTS.glob("*.py"))]))
    checks.append(comparator_cases())
    passed = all(checks)
    print(f"\n{'PASS' if passed else 'FAIL'} qa_sm_data_validation_skill")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
