#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import run_pro_fixture as base
import run_pro_fixture_v2 as amend
import semantic_probe_v3 as semantic
import syntax_ast

ROOT = Path(__file__).resolve().parent
EXTRA = ROOT / "pro_fixture" / "src" / "v2_cases.rs"

base.SemanticLockScope = semantic.SemanticLockScope
base.as_jsonable = semantic.as_jsonable
base.finding_kinds = semantic.finding_kinds
amend.semantic = semantic
amend.base.SemanticLockScope = semantic.SemanticLockScope
amend.base.finding_kinds = semantic.finding_kinds
base.run_tokio_repair = amend.amended_tokio_repair


def run_send_probes_v2() -> list[dict[str, object]]:
    base.BIN_DIR.mkdir(parents=True, exist_ok=True)
    path = base.BIN_DIR / "send_probe.rs"
    expectations = [
        ("std_last_use", False),
        ("std_drop", False),
        ("std_scope", True),
        ("parking_last_use", False),
    ]
    out = []
    try:
        for name, should_compile in expectations:
            path.write_text(base.send_probe_source(name), "utf-8")
            result = base.run(["cargo", "check", "--quiet", "--bin", "send_probe"], timeout=90)
            mentions_send = (
                "cannot be sent between threads safely" in result.stdout
                or "future cannot be sent" in result.stdout
                or "Send" in result.stdout
            )
            passed = (result.returncode == 0) == should_compile
            if not should_compile:
                passed = passed and mentions_send
            out.append({
                "name": name,
                "expected_compile": should_compile,
                "returncode": result.returncode,
                "mentions_send": mentions_send,
                "pass": passed,
                "tail": result.stdout[-1800:],
            })
    finally:
        path.unlink(missing_ok=True)
    return out


base.run_send_probes = run_send_probes_v2


def kinds(analysis, function: str) -> set[str]:
    return semantic.finding_kinds(analysis, function)


def main() -> int:
    started = time.monotonic()
    inherited_rc = base.main()

    with semantic.SemanticLockScope(base.FIXTURE) as analyzer:
        a = analyzer.analyze(EXTRA)
        b = analyzer.analyze(EXTRA)

    relevant = {"sync_lock_across_await", "exclusive_lock_across_await", "read_lock_across_await"}
    expected = {
        "multiline_comment_live": {"exclusive_lock_across_await"},
        "parenthesized_live": {"exclusive_lock_across_await"},
        "arc_clone_owned_live": {"exclusive_lock_across_await"},
        "nested_scope_quiet": set(),
        "std_multiline_live": {"sync_lock_across_await"},
    }
    extra_cases = []
    for fn, want in expected.items():
        actual = kinds(a, fn) & relevant
        extra_cases.append({
            "name": fn,
            "pass": actual == want,
            "actual": sorted(actual),
            "expected": sorted(want),
        })

    candidates = syntax_ast.extract_candidates(EXTRA)
    deterministic = semantic.as_jsonable(a, include_resolution=False) == semantic.as_jsonable(b, include_resolution=False)
    elapsed = time.monotonic() - started
    v3_source = (ROOT / "semantic_probe_v3.py").read_text("utf-8")
    gates = {
        "inherited_20_plus_repairs": inherited_rc == 0,
        "extra_5_of_5": len(extra_cases) == 5 and all(case["pass"] for case in extra_cases),
        "structured_candidates_5": len(candidates) == 5,
        "extra_deterministic": deterministic,
        "no_regex_candidate_backend": "base.ACQUIRE" not in v3_source and "base.MACRO_CALL" not in v3_source,
        "runtime_under_360s": elapsed <= 360.0,
    }
    result = {
        "verdict": "PASS_V2_FIXTURE" if all(gates.values()) else "FAIL_V2_FIXTURE",
        "gates": gates,
        "elapsed_seconds_total": round(elapsed, 3),
        "extra_cases": extra_cases,
        "structured_candidate_count": len(candidates),
        "structured_candidates": [c.__dict__ for c in candidates],
        "syntax_versions": syntax_ast.syntax_versions(),
        "tool_versions": {
            "rustc": base.run(["rustc", "--version"], timeout=10).stdout.strip(),
            "cargo": base.run(["cargo", "--version"], timeout=10).stdout.strip(),
            "rust_analyzer": subprocess.run(["rust-analyzer", "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10).stdout.strip(),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=lambda o: o.__dict__))
    return 0 if result["verdict"] == "PASS_V2_FIXTURE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
