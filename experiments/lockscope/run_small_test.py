#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from lockscope_probe import analyze_text, as_jsonable

JAVIS_REPO = "https://github.com/BEKO2210/Javis.git"
BASELINE = "f0d6b556f459a3757b15e13fde3f5198b7d0826e"
FIXED = "26f6e5db1d47af58e814809505929fa0c16ae1eb"
STATE_PATH = "crates/viz/src/state.rs"


def git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        check=True,
    )
    return result.stdout


def get_state(repo: Path, commit: str) -> str:
    return git("show", f"{commit}:{STATE_PATH}", cwd=repo)


def site(analysis, function: str):
    matches = [s for s in analysis.lock_sites if s.function == function]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one lock site for {function}, got {len(matches)}")
    return matches[0]


def kinds(analysis, function: str | None = None) -> set[str]:
    return {
        str(f["kind"])
        for f in analysis.findings
        if function is None or f.get("function") == function
    }


def evaluate(name: str, condition: bool, details: dict[str, object]) -> dict[str, object]:
    return {"name": name, "pass": bool(condition), "details": details}


def main() -> int:
    cases: list[dict[str, object]] = []

    fixtures = {
        "short_lock": """async fn f(state: &Mutex<Vec<u8>>) {\n    let g = state.lock().await;\n    consume(g.len());\n}\n""",
        "nll_last_use_before_await": """async fn f(state: &Mutex<Vec<u8>>) {\n    let g = state.lock().await;\n    let n = g.len();\n    do_io().await;\n    consume(n);\n}\n""",
        "explicit_drop_before_await": """async fn f(state: &Mutex<Vec<u8>>) {\n    let g = state.lock().await;\n    let n = g.len();\n    drop(g);\n    do_io().await;\n    consume(n);\n}\n""",
        "tokio_exclusive_across_await": """async fn f(state: &Mutex<Vec<u8>>) {\n    let mut g = state.lock().await;\n    do_io().await;\n    g.push(1);\n}\n""",
        "std_sync_across_await": """async fn f(state: &Mutex<Vec<u8>>) {\n    let mut g = state.lock().unwrap();\n    do_io().await;\n    g.push(1);\n}\n""",
        "lock_order_cycle": """async fn one(a: &Mutex<u8>, b: &Mutex<u8>) {\n    let ga = a.lock().await;\n    let gb = b.lock().await;\n    use_both(&ga, &gb);\n}\nasync fn two(a: &Mutex<u8>, b: &Mutex<u8>) {\n    let gb = b.lock().await;\n    let ga = a.lock().await;\n    use_both(&ga, &gb);\n}\n""",
        "consistent_lock_order": """async fn one(a: &Mutex<u8>, b: &Mutex<u8>) {\n    let ga = a.lock().await;\n    let gb = b.lock().await;\n    use_both(&ga, &gb);\n}\nasync fn two(a: &Mutex<u8>, b: &Mutex<u8>) {\n    let ga = a.lock().await;\n    let gb = b.lock().await;\n    use_both(&ga, &gb);\n}\n""",
        "rwlock_read_across_await": """async fn f(state: &RwLock<Vec<u8>>) {\n    let g = state.read().await;\n    do_io().await;\n    consume(g.len());\n}\n""",
    }

    analyses = {name: analyze_text(text) for name, text in fixtures.items()}
    cases.append(evaluate("short_lock", not analyses["short_lock"].findings, as_jsonable(analyses["short_lock"])))
    cases.append(evaluate("nll_last_use_before_await", not analyses["nll_last_use_before_await"].findings, as_jsonable(analyses["nll_last_use_before_await"])))
    cases.append(evaluate("explicit_drop_before_await", not analyses["explicit_drop_before_await"].findings, as_jsonable(analyses["explicit_drop_before_await"])))
    cases.append(evaluate(
        "tokio_exclusive_across_await",
        kinds(analyses["tokio_exclusive_across_await"]) == {"exclusive_lock_across_await"},
        as_jsonable(analyses["tokio_exclusive_across_await"]),
    ))
    cases.append(evaluate(
        "std_sync_across_await",
        kinds(analyses["std_sync_across_await"]) == {"sync_lock_across_await"},
        as_jsonable(analyses["std_sync_across_await"]),
    ))
    cases.append(evaluate(
        "lock_order_cycle",
        analyses["lock_order_cycle"].cycles == [["a", "b"]],
        as_jsonable(analyses["lock_order_cycle"]),
    ))
    cases.append(evaluate(
        "consistent_lock_order",
        not analyses["consistent_lock_order"].cycles,
        as_jsonable(analyses["consistent_lock_order"]),
    ))
    cases.append(evaluate(
        "rwlock_read_across_await",
        kinds(analyses["rwlock_read_across_await"]) == {"read_lock_across_await"},
        as_jsonable(analyses["rwlock_read_across_await"]),
    ))

    with tempfile.TemporaryDirectory(prefix="lockscope-javis-") as tmp:
        root = Path(tmp)
        repo = root / "Javis"
        git("clone", "--quiet", "--filter=blob:none", "--no-checkout", JAVIS_REPO, str(repo))
        git("fetch", "--quiet", "origin", BASELINE, FIXED, cwd=repo)
        old = analyze_text(get_state(repo, BASELINE))
        new = analyze_text(get_state(repo, FIXED))

        old_recall = site(old, "run_recall")
        old_train = site(old, "run_train")
        old_save = site(old, "save_to_file")
        cases.append(evaluate(
            "javis_historical_bottleneck",
            old_recall.mode == "exclusive"
            and old_recall.awaits_while_live >= 3
            and old_recall.span_lines >= 30
            and "exclusive_lock_across_await" in kinds(old, "run_recall")
            and old_train.mode == "exclusive"
            and old_train.awaits_while_live >= 3
            and "exclusive_lock_across_await" in kinds(old, "run_train")
            and "exclusive_lock_across_await" not in kinds(old, "save_to_file")
            and not old.cycles,
            {
                "run_recall": old_recall.__dict__,
                "run_train": old_train.__dict__,
                "save_to_file": old_save.__dict__,
                "cycles": old.cycles,
                "findings": old.findings,
            },
        ))

        new_recall = site(new, "run_recall")
        cases.append(evaluate(
            "javis_historical_fix_transition",
            new_recall.mode == "read"
            and new_recall.awaits_while_live >= 1
            and "exclusive_lock_across_await" not in kinds(new, "run_recall")
            and "read_lock_across_await" in kinds(new, "run_recall")
            and not new.cycles,
            {
                "run_recall": new_recall.__dict__,
                "cycles": new.cycles,
                "findings": new.findings,
            },
        ))

    passed = sum(1 for case in cases if case["pass"])
    result = {
        "verdict": "PASS_SMALL" if passed == len(cases) else "FAIL_SMALL",
        "passed": passed,
        "total": len(cases),
        "baseline_commit": BASELINE,
        "fixed_commit": FIXED,
        "cases": cases,
        "limitations": [
            "prototype uses brace-balanced/textual Rust analysis, not rust-analyzer or a Rust AST",
            "NLL is approximated from last textual guard use",
            "macro-generated acquisitions and non-let acquisition forms are out of scope",
            "this test diagnoses and classifies; it does not yet generate the architectural repair",
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "PASS_SMALL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
