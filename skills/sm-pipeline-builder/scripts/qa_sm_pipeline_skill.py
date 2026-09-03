#!/usr/bin/env python3
"""QA harness for the SourceMedium Pipeline Builder skill package."""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
# The validator module defines the credential patterns; import rather than
# re-declare them so the package scan and the spec check never drift apart.
VALIDATOR = SCRIPTS / "validate_pipeline_spec.py"


def load_validator():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import validate_pipeline_spec

    return validate_pipeline_spec


def run(
    name: str,
    cmd: list[str],
    expect: int = 0,
    forbid_traceback: bool = False,
    require_text: str | None = None,
    forbid_text: str | None = None,
) -> bool:
    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = result.stdout + result.stderr
    ok = result.returncode == expect
    detail = ""
    if ok and forbid_traceback and "Traceback" in output:
        ok, detail = False, "output contained a traceback"
    if ok and require_text is not None and require_text not in output:
        ok, detail = False, f"expected text not found: {require_text!r}"
    if ok and forbid_text is not None and forbid_text in output:
        ok, detail = False, f"forbidden text present: {forbid_text!r}"
    print(f"{'PASS' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"  command: {' '.join(cmd)}")
        print(f"  expected exit: {expect}; actual: {result.returncode}")
        if detail:
            print(f"  reason: {detail}")
        if result.stdout.strip():
            print(f"  stdout: {result.stdout.strip()[:1000]}")
        if result.stderr.strip():
            print(f"  stderr: {result.stderr.strip()[:1000]}")
    return ok


def check(name: str, passed: bool, detail: str = "") -> bool:
    print(f"{'PASS' if passed else 'FAIL'} {name}")
    if not passed and detail:
        print(f"  {detail}")
    return passed


def validate_skill_md() -> bool:
    path = ROOT / "SKILL.md"
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    frontmatter = text.split("---", 2)[1] if "---" in text else ""
    checks = [
        ("SKILL.md exists", path.exists()),
        ("frontmatter exists", bool(match)),
        ("name matches directory", "name: sm-pipeline-builder" in text),
        ("description mentions SourceMedium", "SourceMedium" in frontmatter),
        ("description routes away from analysis", "sm-bigquery-analyst" in frontmatter),
        ("description routes away from dashboards", "sm-dashboard-builder" in frontmatter),
        ("description claims customer-owned dbt", "dbt" in frontmatter),
        ("body references validator script", "scripts/validate_pipeline_spec.py" in text),
        ("body references readiness checklist", "assets/readiness_checklist.md" in text),
        ("body references QA harness", "scripts/qa_sm_pipeline_skill.py" in text),
    ]
    ok = True
    for name, passed in checks:
        ok = check(name, passed) and ok
    return ok


def validate_reference_routing() -> bool:
    """Every reference file is routed to from SKILL.md, and every routed path exists."""
    text = (ROOT / "SKILL.md").read_text()
    on_disk = {path.name for path in (ROOT / "references").glob("*.md")}
    routed = set(re.findall(r"references/([A-Za-z0-9_]+\.md)", text))
    ok = check(
        "every reference file is routed from SKILL.md",
        on_disk <= routed,
        f"orphaned: {sorted(on_disk - routed)}",
    )
    ok = check(
        "every routed reference file exists",
        routed <= on_disk,
        f"dangling: {sorted(routed - on_disk)}",
    ) and ok

    # Internal asset/script paths named anywhere in the package must resolve.
    dangling: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir() or path.suffix not in (".md", ".yaml", ".json"):
            continue
        # Skip paths qualified by another skill's directory (sm-dashboard-builder/assets/...).
        pattern = r"(?<![\w/-])(?:assets|scripts|evals)/[A-Za-z0-9_./-]+"
        for ref in re.findall(pattern, path.read_text()):
            target = ref.rstrip(".,;:)")
            if not (ROOT / target).exists():
                dangling.append(f"{path.relative_to(ROOT)} -> {target}")
    return check("no dangling asset/script paths", not dangling, "; ".join(dangling)) and ok


def validate_no_secrets() -> bool:
    """The package must never carry a credential value, only secret names."""
    patterns = load_validator().CREDENTIAL_PATTERNS
    hits: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        # Only the module that defines the patterns is exempt from matching them.
        if path == VALIDATOR:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in patterns:
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT)} ({label})")
                break
    return check("no credential values in package", not hits, f"found in: {hits}")


def validate_shape_fuzz() -> bool:
    """No spec shape may raise out of validate(): malformed input is reported, not thrown.

    Every field of a hand-written YAML spec can arrive as the wrong type. This
    mutates every path in the shipped template to every wrong type and calls
    validate() directly, so a missing shape guard surfaces here instead of as a
    traceback in front of an operator.
    """
    try:
        import yaml
    except ImportError:
        return check("shape fuzz over spec tree (skipped: PyYAML unavailable)", True)

    validate = load_validator().validate
    spec = yaml.safe_load((ROOT / "assets" / "pipeline_spec_template.yaml").read_text())
    bad_values = [None, "str", 42, 3.14, True, [], ["a"], {}, {"k": "v"}, [{"a": 1}], [[1]], [None]]

    def paths(node, prefix=()):
        if isinstance(node, dict):
            for key, value in node.items():
                yield prefix + (key,)
                yield from paths(value, prefix + (key,))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield prefix + (index,)
                yield from paths(value, prefix + (index,))

    failures: list[str] = []
    tree_paths = list(paths(spec))
    for path in tree_paths:
        for bad in bad_values:
            mutant = copy.deepcopy(spec)
            cursor = mutant
            for step in path[:-1]:
                cursor = cursor[step]
            cursor[path[-1]] = bad
            try:
                validate(mutant)
            except Exception as exc:
                failures.append(f"{'.'.join(map(str, path))}={bad!r} -> {type(exc).__name__}: {exc}")
    return check(
        f"shape fuzz over spec tree ({len(tree_paths)} paths x {len(bad_values)} types)",
        not failures,
        "; ".join(failures[:5]),
    )


def validate_json_files() -> bool:
    ok = True
    for path in [ROOT / "evals" / "evals.json"]:
        try:
            json.loads(path.read_text())
            print(f"PASS valid JSON: {path.relative_to(ROOT)}")
        except Exception as exc:
            print(f"FAIL valid JSON: {path.relative_to(ROOT)}: {exc}")
            ok = False
    return ok


def validate_evals() -> bool:
    data = json.loads((ROOT / "evals" / "evals.json").read_text())
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


def write(tempdir: str, name: str, body: str) -> str:
    path = Path(tempdir) / name
    path.write_text(body, encoding="utf-8")
    return str(path)


# A minimal valid stream, reused so each case varies exactly one thing.
CLEAN_SOURCE = (
    "pipeline: p\n"
    "source:\n"
    "  name: x\n"
    "  auth_secret: MY_API_KEY_PROD\n"
    "  auth_failure_mode: page on first occurrence\n"
    "  rate_limit: {model: rps, value: 5}\n"
    "  pagination: {stop_condition: empty page}\n"
)
CLEAN_DEST = "destination: {project: p, dataset_raw: r}\n"
CLEAN_STREAM_TAIL = "    bootstrap_window: 2024-12-01/2024-12-31\n    deletes: none\n    coverage_check: row floor\n"
# Appended to any fixture that must pass --strict: the cost ceiling is a
# declaration warning like the per-stream ones, so a clean spec declares it.
CLEAN_COST = "cost: {backfill_max_windows_per_run: 30, query_max_bytes_billed: 20GB}\n"

# Synthetic credentials for the detection tests, assembled at runtime so that
# validate_no_secrets() still scans this file instead of having to exempt it.
FAKE_SHOPIFY_TOKEN = "shpat" + "_" + "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
FAKE_JWT = "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0." + "sig"
FAKE_AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"


def spec_validator_cases() -> bool:
    validator = str(SCRIPTS / "validate_pipeline_spec.py")
    template = str(ROOT / "assets" / "pipeline_spec_template.yaml")
    ok = True
    ok &= run("template spec validates", [sys.executable, validator, template])
    ok &= run("template spec validates --strict", [sys.executable, validator, template, "--strict"])

    with tempfile.TemporaryDirectory() as tempdir:
        def case(name: str, body: str, expect: int = 2, **kwargs) -> bool:
            path = write(tempdir, re.sub(r"\W+", "_", name) + ".yaml", body)
            args = [sys.executable, validator, path]
            if kwargs.pop("strict", False):
                args.append("--strict")
            return run(name, args, expect=expect, **kwargs)

        # --- required declarations -------------------------------------------------
        ok &= case(
            "missing primary key rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [id]\n"
            "    load: {mode: merge}\n    incremental: {cursor_field: updated_at, overlap: 24h}\n",
        )
        ok &= case(
            "missing grain rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    primary_key: [id]\n"
            "    load: {mode: merge}\n    incremental: {cursor_field: updated_at, overlap: 24h}\n",
        )
        ok &= case(
            "merge without cursor rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: merge}\n",
        )
        ok &= case(
            "malformed overlap rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: merge}\n    incremental: {cursor_field: updated_at, overlap: 48 hours}\n",
        )
        ok &= case(
            "zero overlap rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: merge}\n    incremental: {cursor_field: updated_at, overlap: 0h}\n",
        )
        ok &= case(
            "negative overlap rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: merge}\n    incremental: {cursor_field: updated_at, overlap: -5h}\n",
        )
        ok &= case(
            "duplicate stream names rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n"
            "  - {name: s, grain: [id], primary_key: [id], load: {mode: snapshot}}\n"
            "  - {name: s, grain: [id], primary_key: [id], load: {mode: snapshot}}\n",
        )
        ok &= case(
            "unknown load.mode rejected",
            CLEAN_SOURCE + CLEAN_DEST
            + "streams:\n  - {name: s, grain: [id], primary_key: [id], load: {mode: upsert}}\n",
        )
        ok &= case(
            "snapshot without cursor accepted",
            CLEAN_SOURCE + CLEAN_DEST
            + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: snapshot}\n" + CLEAN_STREAM_TAIL + CLEAN_COST,
            expect=0,
            strict=True,
        )

        # --- append_restate needs a window, not just a horizon ---------------------
        ok &= case(
            "append_restate without restatement_days rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: append_restate}\n    incremental: {window_column: report_date}\n",
        )
        ok &= case(
            "append_restate without window_column rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: append_restate}\n    restatement_days: 14\n",
            require_text="window_column",
        )
        ok &= case(
            "append_restate complete accepted",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: append_restate}\n    restatement_days: 14\n"
            "    incremental: {window_column: report_date}\n" + CLEAN_STREAM_TAIL + CLEAN_COST,
            expect=0,
            strict=True,
        )

        # --- hard rule 2: never write to sm_* -------------------------------------
        ok &= case(
            "sm_* destination dataset rejected",
            CLEAN_SOURCE + "destination: {project: sm-acme, dataset_raw: sm_transformed_v2}\n"
            "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: snapshot}\n" + CLEAN_STREAM_TAIL,
            require_text="never write to SourceMedium",
        )
        ok &= case(
            "sm_* rejected even without --strict",
            CLEAN_SOURCE + "destination: {project: sm-acme, dataset_marts: SM_Marts}\n"
            "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: snapshot}\n" + CLEAN_STREAM_TAIL,
        )

        # --- hard rule 13: specs name secrets, never carry them --------------------
        ok &= case(
            "credential value in auth_secret rejected",
            "pipeline: p\nsource:\n  name: x\n"
            f"  auth_secret: {FAKE_SHOPIFY_TOKEN}\n" + CLEAN_DEST
            + "streams:\n  - {name: s, grain: [id], primary_key: [id], load: {mode: snapshot}}\n",
            require_text="never carry them",
        )
        ok &= case(
            "credential nested anywhere rejected",
            "pipeline: p\nsource:\n  name: x\n  headers:\n"
            f'    Authorization: "Bearer {FAKE_JWT}"\n' + CLEAN_DEST
            + "streams:\n  - {name: s, grain: [id], primary_key: [id], load: {mode: snapshot}}\n",
            require_text="source.headers.Authorization",
        )
        ok &= case(
            "AWS access key id rejected",
            "pipeline: p\nsource: {name: x, auth_secret: " + FAKE_AWS_KEY + "}\n" + CLEAN_DEST
            + "streams:\n  - {name: s, grain: [id], primary_key: [id], load: {mode: snapshot}}\n",
        )
        # Secret NAMES must not trip the scanner. These are the shapes people use.
        ok &= case(
            "GCP secret resource path accepted",
            "pipeline: p\nsource:\n  name: x\n"
            "  auth_secret: projects/123456789012/secrets/loyalty-api-key/versions/latest\n"
            "  auth_failure_mode: page\n  rate_limit: {model: rps, value: 5}\n"
            "  pagination: {stop_condition: empty page}\n" + CLEAN_DEST
            + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: snapshot}\n" + CLEAN_STREAM_TAIL + CLEAN_COST,
            expect=0,
            strict=True,
        )
        ok &= case(
            "AWS secret ARN accepted",
            "pipeline: p\nsource:\n  name: x\n"
            '  auth_secret: "arn:aws:secretsmanager:us-east-1:123456789012:secret:loyalty-AbCdEf"\n'
            "  auth_failure_mode: page\n  rate_limit: {model: rps, value: 5}\n"
            "  pagination: {stop_condition: empty page}\n" + CLEAN_DEST
            + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: snapshot}\n" + CLEAN_STREAM_TAIL + CLEAN_COST,
            expect=0,
            strict=True,
        )

        ok &= case(
            "opaque column names under *_key fields are not flagged as secrets",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n"
            "    grain: [a1b2c3d4e5f6g7h8i9j0]\n    primary_key: [a1b2c3d4e5f6g7h8i9j0]\n"
            "    load: {mode: snapshot}\n" + CLEAN_STREAM_TAIL + CLEAN_COST,
            expect=0,
            strict=True,
            forbid_text="credential",
        )

        # --- the key must come from the grain --------------------------------------
        ok &= case(
            "primary key not derivable from grain rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [member_id, txn_id]\n"
            "    primary_key: [unrelated_col]\n    load: {mode: snapshot}\n" + CLEAN_STREAM_TAIL,
            require_text="not derivable from `grain`",
        )
        ok &= case(
            "declared surrogate key accepted",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [report_date, campaign_id]\n"
            "    primary_key: [row_key]\n"
            "    surrogate_key: {name: row_key, from: [report_date, campaign_id]}\n"
            "    load: {mode: snapshot}\n    business_date_close: {zone_source: tz}\n" + CLEAN_STREAM_TAIL + CLEAN_COST,
            expect=0,
            strict=True,
        )
        ok &= case(
            "surrogate hashing outside the grain rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [report_date, campaign_id]\n"
            "    primary_key: [row_key]\n"
            "    surrogate_key: {name: row_key, from: [report_date, unrelated]}\n"
            "    load: {mode: snapshot}\n",
        )
        ok &= case(
            "surrogate missing from primary key rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [report_date, campaign_id]\n"
            "    primary_key: [report_date]\n"
            "    surrogate_key: {name: row_key, from: [report_date, campaign_id]}\n"
            "    load: {mode: snapshot}\n",
        )

        # --- external destinations --------------------------------------------------
        ok &= case(
            "external destination without system/pii rejected",
            CLEAN_SOURCE + "destination: {kind: external}\n"
            "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: snapshot}\n" + CLEAN_STREAM_TAIL,
            require_text="destination.pii",
        )
        ok &= case(
            "external destination complete accepted",
            CLEAN_SOURCE + "destination:\n  kind: external\n  system: snowflake-prod ANALYTICS.EXPORT\n"
            "  pii: none\n"
            "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: snapshot}\n" + CLEAN_STREAM_TAIL + CLEAN_COST,
            expect=0,
            strict=True,
        )
        ok &= case(
            "unknown destination.kind rejected",
            CLEAN_SOURCE + "destination: {kind: s3, system: bucket}\n"
            "streams:\n  - {name: s, grain: [id], primary_key: [id], load: {mode: snapshot}}\n",
        )

        # --- money scale 0 is a real scale, not a missing one ----------------------
        ok &= case(
            "money scale 0 does not warn",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: snapshot}\n"
            "    money_fields:\n      - {name: amount_jpy, unit: whole_yen, scale: 0}\n"
            + CLEAN_STREAM_TAIL + CLEAN_COST,
            expect=0,
            strict=True,
            forbid_text="`scale` undeclared",
        )
        ok &= case(
            "money missing unit rejected",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n"
            "    load: {mode: snapshot}\n    money_fields:\n      - {name: amount, scale: 2}\n",
        )

        # --- malformed shapes exit 2 with a message, never a traceback -------------
        malformed = {
            "load as scalar": "    load: merge\n",
            "load as list": "    load: [merge]\n",
            "incremental as list": "    load: {mode: merge}\n    incremental: [updated_at, 48h]\n",
            "money_fields as mapping": "    load: {mode: snapshot}\n    money_fields: {name: a, unit: b}\n",
        }
        for label, tail in malformed.items():
            ok &= case(
                f"{label} exits 2 without traceback",
                CLEAN_SOURCE + CLEAN_DEST
                + "streams:\n  - name: s\n    grain: [id]\n    primary_key: [id]\n" + tail,
                forbid_traceback=True,
            )
        ok &= case(
            "source.pagination as scalar exits 2 without traceback",
            "pipeline: p\nsource:\n  name: x\n  pagination: cursor\n" + CLEAN_DEST
            + "streams:\n  - {name: s, grain: [id], primary_key: [id], load: {mode: snapshot}}\n",
            forbid_traceback=True,
        )
        ok &= case(
            "stream as scalar exits 2 without traceback",
            CLEAN_SOURCE + CLEAN_DEST + "streams:\n  - just-a-string\n",
            forbid_traceback=True,
        )
        ok &= case(
            "top-level list exits 2 without traceback",
            "- a\n- b\n",
            forbid_traceback=True,
        )
        ok &= case("empty file exits 2 without traceback", "", forbid_traceback=True)

        bad_yaml = write(tempdir, "bad.yaml", "pipeline: [unclosed\n  bad: :")
        ok &= run(
            "malformed YAML exits 2 without traceback",
            [sys.executable, validator, bad_yaml],
            expect=2,
            forbid_traceback=True,
        )
        bad_json = write(tempdir, "bad.json", '{"pipeline": "p", "streams":')
        ok &= run(
            "malformed JSON exits 2 without traceback",
            [sys.executable, validator, bad_json],
            expect=2,
            forbid_traceback=True,
        )
        ok &= run(
            "missing file exits 2 without traceback",
            [sys.executable, validator, str(Path(tempdir) / "does-not-exist.yaml")],
            expect=2,
            forbid_traceback=True,
        )

        # --- JSON specs and the warning/strict split --------------------------------
        json_ok = write(
            tempdir,
            "spec_ok.json",
            json.dumps(
                {
                    "pipeline": "ok",
                    "source": {"name": "x"},
                    "destination": {"project": "p"},
                    "streams": [
                        {"name": "s", "grain": ["id"], "primary_key": ["id"], "load": {"mode": "snapshot"}}
                    ],
                }
            ),
        )
        ok &= run("JSON spec accepted", [sys.executable, validator, json_ok])

        warn_only = write(
            tempdir,
            "warn_only.yaml",
            "pipeline: ok\nsource: {name: x}\ndestination: {project: p, dataset_raw: r}\n"
            "streams:\n  - name: events\n    grain: [event_date, id]\n    primary_key: [event_date, id]\n"
            "    load: {mode: snapshot}\n    partition: event_date\n",
        )
        ok &= run("warnings pass without --strict", [sys.executable, validator, warn_only])
        ok &= run("warnings fail with --strict", [sys.executable, validator, warn_only, "--strict"], expect=2)
    return ok


def main() -> int:
    checks: list[bool] = []
    checks.append(validate_skill_md())
    checks.append(validate_reference_routing())
    checks.append(validate_no_secrets())
    checks.append(validate_shape_fuzz())
    checks.append(validate_json_files())
    checks.append(validate_evals())
    checks.append(run("scripts compile", [sys.executable, "-m", "py_compile", *map(str, SCRIPTS.glob("*.py"))]))
    checks.append(run("validator --help", [sys.executable, str(SCRIPTS / "validate_pipeline_spec.py"), "--help"]))
    checks.append(spec_validator_cases())

    passed = all(checks)
    print(f"\n{'PASS' if passed else 'FAIL'} qa_sm_pipeline_skill")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
