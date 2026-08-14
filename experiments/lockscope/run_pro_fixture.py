#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from repair_defer_lock import repair_file
from semantic_probe import SemanticLockScope, as_jsonable, finding_kinds

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "pro_fixture"
LIB = FIXTURE / "src" / "lib.rs"
BIN_DIR = FIXTURE / "src" / "bin"
TARGET = ROOT / ".target-pro-fixture"


def run(cmd: list[str], cwd: Path = FIXTURE, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(TARGET)
    env["CARGO_TERM_COLOR"] = "never"
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def require_ok(name: str, result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    if result.returncode != 0:
        raise AssertionError(f"{name} failed rc={result.returncode}\n{result.stdout[-4000:]}")
    return {"name": name, "returncode": result.returncode, "tail": result.stdout[-1200:]}


def check_case(name: str, condition: bool, details: object) -> dict[str, object]:
    return {"name": name, "pass": bool(condition), "details": details}


def kinds(analysis, function: str) -> set[str]:
    return finding_kinds(analysis, function)


def send_probe_source(kind: str) -> str:
    if kind == "std_last_use":
        body = """
use std::hint::black_box;
use std::sync::{Arc, Mutex};
#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let worker = Arc::clone(&state);
    tokio::spawn(async move {
        let guard = worker.lock().unwrap();
        let n = guard.len();
        tokio::task::yield_now().await;
        black_box(n)
    }).await.unwrap();
}
"""
    elif kind == "std_drop":
        body = """
use std::hint::black_box;
use std::sync::{Arc, Mutex};
#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let worker = Arc::clone(&state);
    tokio::spawn(async move {
        let guard = worker.lock().unwrap();
        let n = guard.len();
        drop(guard);
        tokio::task::yield_now().await;
        black_box(n)
    }).await.unwrap();
}
"""
    elif kind == "std_scope":
        body = """
use std::hint::black_box;
use std::sync::{Arc, Mutex};
#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let worker = Arc::clone(&state);
    tokio::spawn(async move {
        let n = {
            let guard = worker.lock().unwrap();
            guard.len()
        };
        tokio::task::yield_now().await;
        black_box(n)
    }).await.unwrap();
}
"""
    elif kind == "parking_last_use":
        body = """
use parking_lot::Mutex;
use std::hint::black_box;
use std::sync::Arc;
#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let worker = Arc::clone(&state);
    tokio::spawn(async move {
        let guard = worker.lock();
        let n = guard.len();
        tokio::task::yield_now().await;
        black_box(n)
    }).await.unwrap();
}
"""
    else:
        raise KeyError(kind)
    return body.lstrip()


def run_send_probes() -> list[dict[str, object]]:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    path = BIN_DIR / "send_probe.rs"
    expectations = [
        ("std_last_use", False),
        ("std_drop", True),
        ("std_scope", True),
        ("parking_last_use", False),
    ]
    out: list[dict[str, object]] = []
    try:
        for name, should_compile in expectations:
            path.write_text(send_probe_source(name), "utf-8")
            result = run(["cargo", "check", "--quiet", "--bin", "send_probe"], timeout=90)
            compiler_mentions_send = (
                "cannot be sent between threads safely" in result.stdout
                or "future cannot be sent" in result.stdout
                or "Send" in result.stdout
            )
            passed = (result.returncode == 0) == should_compile
            if not should_compile:
                passed = passed and compiler_mentions_send
            out.append(
                {
                    "name": name,
                    "expected_compile": should_compile,
                    "returncode": result.returncode,
                    "mentions_send": compiler_mentions_send,
                    "pass": passed,
                    "tail": result.stdout[-1800:],
                }
            )
    finally:
        if path.exists():
            path.unlink()
    return out


def tokio_repair_source() -> str:
    return """
use std::sync::Arc;
use tokio::sync::{Barrier, Mutex};
use tokio::time::{timeout, Duration};

async fn worker(state: Arc<Mutex<Vec<u8>>>, barrier: Arc<Barrier>) {
    let mut guard = state.lock().await;
    barrier.wait().await;
    guard.push(1);
}

#[tokio::main(flavor = "multi_thread", worker_threads = 4)]
async fn main() {
    let state = Arc::new(Mutex::new(Vec::new()));
    let barrier = Arc::new(Barrier::new(4));
    let mut handles = Vec::new();
    for _ in 0..4 {
        let state = Arc::clone(&state);
        let barrier = Arc::clone(&barrier);
        handles.push(tokio::spawn(worker(state, barrier)));
    }
    let joined = async move {
        for handle in handles {
            handle.await.unwrap();
        }
    };
    if timeout(Duration::from_millis(300), joined).await.is_err() {
        std::process::exit(3);
    }
    assert_eq!(state.lock().await.len(), 4);
}
""".lstrip()


def analyze_once(path: Path):
    with SemanticLockScope(FIXTURE) as analyzer:
        return analyzer.analyze(path)


def run_tokio_repair() -> dict[str, object]:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    path = BIN_DIR / "tokio_repair_probe.rs"
    original = tokio_repair_source()
    path.write_text(original, "utf-8")
    try:
        before_analysis = analyze_once(path)
        before_kinds = kinds(before_analysis, "worker")
        before_run = run(["cargo", "run", "--quiet", "--bin", "tokio_repair_probe"], timeout=30)
        repair = repair_file(path)
        repaired = path.read_text("utf-8")
        after_analysis = analyze_once(path)
        after_kinds = kinds(after_analysis, "worker")
        after_run = run(["cargo", "run", "--quiet", "--bin", "tokio_repair_probe"], timeout=30)
        clippy = run(
            ["cargo", "clippy", "--quiet", "--bin", "tokio_repair_probe", "--", "-D", "warnings"],
            timeout=60,
        )
        checks = {
            "before_detected": "exclusive_lock_across_await" in before_kinds,
            "before_timed_out": before_run.returncode == 3,
            "repair_created": repair is not None,
            "after_finding_cleared": "exclusive_lock_across_await" not in after_kinds,
            "after_completed": after_run.returncode == 0,
            "clippy_clean": clippy.returncode == 0,
            "unsafe_not_introduced": ("unsafe" not in repaired) or ("unsafe" in original),
        }
        return {
            "pass": all(checks.values()),
            "checks": checks,
            "repair": None if repair is None else repair.__dict__,
            "before_findings": before_analysis.findings,
            "after_findings": after_analysis.findings,
            "before_run_tail": before_run.stdout[-1000:],
            "after_run_tail": after_run.stdout[-1000:],
            "clippy_tail": clippy.stdout[-1000:],
        }
    finally:
        if path.exists():
            path.unlink()


def main() -> int:
    started = time.monotonic()
    evidence: dict[str, object] = {}
    evidence["cargo_check"] = require_ok("fixture cargo check", run(["cargo", "check", "--quiet"], timeout=120))
    evidence["runtime_tests"] = require_ok(
        "drop-semantics tests",
        run(["cargo", "test", "--quiet", "--test", "drop_semantics"], timeout=120),
    )

    with SemanticLockScope(FIXTURE) as analyzer:
        analysis_a = analyzer.analyze(LIB)
        analysis_b = analyzer.analyze(LIB)

    normalized_a = as_jsonable(analysis_a, include_resolution=False)
    normalized_b = as_jsonable(analysis_b, include_resolution=False)
    deterministic = normalized_a == normalized_b

    semantic_cases: list[dict[str, object]] = []
    def expect(name: str, function: str, expected: set[str]) -> None:
        actual = kinds(analysis_a, function)
        relevant = actual & {
            "sync_lock_across_await",
            "exclusive_lock_across_await",
            "read_lock_across_await",
        }
        semantic_cases.append(check_case(name, relevant == expected, {"function": function, "actual": sorted(relevant), "expected": sorted(expected)}))

    expect("01_tokio_mutex_live", "tokio_exclusive_live", {"exclusive_lock_across_await"})
    expect("02_tokio_alias_live", "tokio_alias_live", {"exclusive_lock_across_await"})
    expect("03_tokio_owned_live", "tokio_owned_live", {"exclusive_lock_across_await"})
    expect("04_tokio_last_use_drop_scope", "tokio_last_use_only", {"exclusive_lock_across_await"})
    expect("05_tokio_explicit_drop", "tokio_explicit_drop", set())
    expect("06_tokio_inner_scope", "tokio_scope", set())
    expect("07_rw_read_live", "rw_read_live", {"read_lock_across_await"})
    expect("08_rw_write_live", "rw_write_live", {"exclusive_lock_across_await"})
    expect("09_std_live", "std_live", {"sync_lock_across_await"})
    expect("10_std_last_use_drop_scope", "std_last_use", {"sync_lock_across_await"})
    expect("11_std_explicit_drop", "std_explicit_drop", set())
    expect("12_std_inner_scope", "std_scope", set())
    expect("13_parking_lot_live", "parking_live", {"sync_lock_across_await"})
    expect("14_multiline_tokio", "multiline_live", {"exclusive_lock_across_await"})
    expect("15_fake_lock_ignored", "fake_lock_method", set())

    cycles = [sorted(cycle) for cycle in analysis_a.cycles]
    semantic_cases.append(check_case("16_two_node_cycle", ["self.a2", "self.b2"] in cycles, cycles))
    semantic_cases.append(check_case("17_three_node_cycle", ["self.a3", "self.b3", "self.c3"] in cycles, cycles))
    semantic_cases.append(check_case("18_self_cycle", ["self.self_lock"] in cycles, cycles))
    semantic_cases.append(check_case("19_consistent_order_no_cycle", ["self.left", "self.right"] not in cycles, cycles))
    macro_kinds = kinds(analysis_a, "macro_generated_live")
    semantic_cases.append(
        check_case(
            "20_macro_generated_tokio",
            "exclusive_lock_across_await" in macro_kinds
            and any(site.function == "macro_generated_live" and site.origin == "macro" for site in analysis_a.lock_sites),
            {"kinds": sorted(macro_kinds), "macro_sites": [site.__dict__ for site in analysis_a.lock_sites if site.function == "macro_generated_live"]},
        )
    )

    send_probes = run_send_probes()
    repair = run_tokio_repair()
    elapsed = time.monotonic() - started

    gates = {
        "semantic_20_of_20": len(semantic_cases) == 20 and all(case["pass"] for case in semantic_cases),
        "deterministic": deterministic,
        "compiler_send_4_of_4": len(send_probes) == 4 and all(item["pass"] for item in send_probes),
        "tokio_repair": bool(repair["pass"]),
        "runtime_budget_under_300s": elapsed <= 300.0,
    }
    result = {
        "verdict": "PASS_FIXTURE" if all(gates.values()) else "FAIL_FIXTURE",
        "gates": gates,
        "elapsed_seconds": round(elapsed, 3),
        "semantic_cases": semantic_cases,
        "deterministic": deterministic,
        "compiler_send_probes": send_probes,
        "tokio_repair": repair,
        "analysis": normalized_a,
        "tool_versions": {
            "rustc": run(["rustc", "--version"], timeout=10).stdout.strip(),
            "cargo": run(["cargo", "--version"], timeout=10).stdout.strip(),
            "rust_analyzer": subprocess.run(["rust-analyzer", "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10).stdout.strip(),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "PASS_FIXTURE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
