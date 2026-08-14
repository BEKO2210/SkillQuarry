#!/usr/bin/env python3
"""Amended pro-fixture runner.

A1: use semantic_probe_v2 evidence collection.
A2: isolate the Tokio repair proof in its own tiny Cargo package so strict
Clippy evaluates the repaired target rather than the intentionally hazardous
semantic-ground-truth library.

No expected case, compiler expectation, count, or runtime threshold changes.
In particular, `std_drop` is still expected by the preregistration to compile;
Rust 1.97.1 disproved that expectation in run 1 and it remains a failing gate.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import run_pro_fixture as base
import semantic_probe_v2 as semantic
from repair_defer_lock import repair_file

base.SemanticLockScope = semantic.SemanticLockScope
base.as_jsonable = semantic.as_jsonable
base.finding_kinds = semantic.finding_kinds


def analyze_at(root: Path, path: Path):
    with semantic.SemanticLockScope(root) as analyzer:
        return analyzer.analyze(path)


def amended_tokio_repair() -> dict[str, object]:
    repair_root = base.ROOT / ".tokio-repair-standalone"
    if repair_root.exists():
        shutil.rmtree(repair_root)
    (repair_root / "src").mkdir(parents=True)
    (repair_root / "Cargo.toml").write_text(
        """[package]\nname = \"lockscope-tokio-repair\"\nversion = \"0.1.0\"\nedition = \"2021\"\npublish = false\n\n[dependencies]\ntokio = { version = \"=1.47.1\", features = [\"rt-multi-thread\", \"macros\", \"sync\", \"time\"] }\n""",
        "utf-8",
    )
    path = repair_root / "src" / "main.rs"
    original = base.tokio_repair_source()
    path.write_text(original, "utf-8")
    target = base.TARGET / "standalone-repair"

    def run_here(cmd: list[str], timeout: int = 60):
        import os
        import subprocess
        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = str(target)
        env["CARGO_TERM_COLOR"] = "never"
        return subprocess.run(
            cmd,
            cwd=repair_root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )

    try:
        precheck = run_here(["cargo", "check", "--quiet"], 90)
        before_analysis = analyze_at(repair_root, path)
        before_kinds = semantic.finding_kinds(before_analysis, "worker")
        before_run = run_here(["cargo", "run", "--quiet"], 30)
        repair = repair_file(path)
        repaired = path.read_text("utf-8")
        after_analysis = analyze_at(repair_root, path)
        after_kinds = semantic.finding_kinds(after_analysis, "worker")
        after_run = run_here(["cargo", "run", "--quiet"], 30)
        clippy = run_here(["cargo", "clippy", "--quiet", "--", "-D", "warnings"], 60)
        checks = {
            "standalone_baseline_compiles": precheck.returncode == 0,
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
        shutil.rmtree(repair_root, ignore_errors=True)


base.run_tokio_repair = amended_tokio_repair

if __name__ == "__main__":
    raise SystemExit(base.main())
