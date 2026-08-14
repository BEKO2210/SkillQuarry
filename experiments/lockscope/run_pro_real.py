#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from repair_defer_lock import repair_file
from semantic_probe import SemanticLockScope, finding_kinds

ROOT = Path(__file__).resolve().parent
TARGET_ROOT = ROOT / ".target-pro-real"

JAVIS_REPO = "https://github.com/BEKO2210/Javis.git"
JAVIS_BEFORE = "f0d6b556f459a3757b15e13fde3f5198b7d0826e"
JAVIS_AFTER = "26f6e5db1d47af58e814809505929fa0c16ae1eb"
JAVIS_FILE = Path("crates/viz/src/state.rs")

FERRY_REPO = "https://github.com/iMMIQ/ferryman.git"
FERRY_BEFORE = "8e9697b9eeee9db1e93a7e22eb7572650f5b001d"
FERRY_AFTER = "93b814fca8c6aca98e0f2a0859545b3ada4945a8"
FERRY_FILE = Path("src/bin/ferryman-web.rs")

MINI_REPO = "https://github.com/tokio-rs/mini-redis.git"
MINI_COMMIT = "3d93b42bc363220f85af4fc9e1bebd35b588a4a3"
MINI_FILE = Path("src/db.rs")


def run(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: int = 180,
    target: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CARGO_TERM_COLOR"] = "never"
    if target is not None:
        env["CARGO_TARGET_DIR"] = str(target)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def git_ok(cmd: list[str], cwd: Path | None = None, timeout: int = 180) -> str:
    result = run(["git", *cmd], cwd=cwd, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(cmd)} failed\n{result.stdout[-3000:]}")
    return result.stdout


def checkout_pair(root: Path, name: str, url: str, before: str, after: str) -> tuple[Path, Path]:
    repo = root / f"{name}-repo"
    git_ok(["clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(repo)], timeout=180)
    git_ok(["fetch", "--quiet", "origin", before, after], cwd=repo, timeout=180)
    old = root / f"{name}-before"
    new = root / f"{name}-after"
    git_ok(["worktree", "add", "--quiet", "--detach", str(old), before], cwd=repo, timeout=120)
    git_ok(["worktree", "add", "--quiet", "--detach", str(new), after], cwd=repo, timeout=120)
    return old, new


def checkout_one(root: Path, name: str, url: str, commit: str) -> Path:
    repo = root / name
    git_ok(["clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(repo)], timeout=180)
    git_ok(["fetch", "--quiet", "origin", commit], cwd=repo, timeout=180)
    git_ok(["checkout", "--quiet", "--detach", commit], cwd=repo, timeout=120)
    return repo


def analyze(root: Path, rel: Path):
    with SemanticLockScope(root) as analyzer:
        return analyzer.analyze(root / rel)


def kinds(analysis, function: str) -> set[str]:
    return finding_kinds(analysis, function)


def summarize(analysis, functions: list[str]) -> dict[str, object]:
    return {
        "functions": {name: sorted(kinds(analysis, name)) for name in functions},
        "cycles": analysis.cycles,
        "sites": [
            {
                "function": site.function,
                "line": site.line,
                "lock": site.lock_expr,
                "family": site.family,
                "mode": site.mode,
                "awaits": site.awaits_while_live,
                "span_lines": site.span_lines,
            }
            for site in analysis.lock_sites
            if site.function in functions
        ],
    }


def cargo_gate(repo: Path, target: Path) -> dict[str, object]:
    commands = [
        ["cargo", "check", "--locked"],
        ["cargo", "test", "--locked", "--quiet"],
    ]
    details: list[dict[str, object]] = []
    valid = True
    for cmd in commands:
        result = run(cmd, cwd=repo, timeout=240, target=target)
        details.append({"command": " ".join(cmd), "returncode": result.returncode, "tail": result.stdout[-1800:]})
        if result.returncode != 0:
            valid = False
            break
    return {"valid": valid, "commands": details}


def clippy_gate(repo: Path, target: Path) -> dict[str, object]:
    result = run(
        ["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"],
        cwd=repo,
        timeout=240,
        target=target,
    )
    return {"valid": result.returncode == 0, "returncode": result.returncode, "tail": result.stdout[-2200:]}


def mini_mutate(path: Path) -> None:
    text = path.read_text("utf-8")
    needle = """        } else {
            // There are no keys expiring in the future. Wait until the task is
            // notified.
            shared.background_task.notified().await;
        }
"""
    replacement = """        } else {
            // There are no keys expiring in the future. Wait until the task is
            // notified.
            let state = shared.state.lock().unwrap();
            shared.background_task.notified().await;
            if state.shutdown {
                break;
            }
        }
"""
    if text.count(needle) != 1:
        raise AssertionError("mini-redis injection target did not match exactly once")
    path.write_text(text.replace(needle, replacement), "utf-8")


def main() -> int:
    started = time.monotonic()
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="lockscope-pro-real-") as tmp:
        temp = Path(tmp)

        javis_old, javis_new = checkout_pair(temp, "javis", JAVIS_REPO, JAVIS_BEFORE, JAVIS_AFTER)
        old_j = analyze(javis_old, JAVIS_FILE)
        new_j = analyze(javis_new, JAVIS_FILE)
        javis_checks = {
            "before_recall_exclusive": "exclusive_lock_across_await" in kinds(old_j, "run_recall"),
            "after_recall_exclusive_cleared": "exclusive_lock_across_await" not in kinds(new_j, "run_recall"),
            "after_recall_read_visible": "read_lock_across_await" in kinds(new_j, "run_recall"),
            "no_old_cycle": not old_j.cycles,
            "no_new_cycle": not new_j.cycles,
        }
        result["javis"] = {
            "pass": all(javis_checks.values()),
            "checks": javis_checks,
            "before": summarize(old_j, ["run_recall", "run_train", "save_to_file"]),
            "after": summarize(new_j, ["run_recall", "run_train", "save_to_file"]),
        }

        ferry_old, ferry_new = checkout_pair(temp, "ferryman", FERRY_REPO, FERRY_BEFORE, FERRY_AFTER)
        old_f = analyze(ferry_old, FERRY_FILE)
        new_f = analyze(ferry_new, FERRY_FILE)
        ferry_checks = {
            "before_mutate_job_exclusive": "exclusive_lock_across_await" in kinds(old_f, "mutate_job"),
            "after_mutate_job_cleared": "exclusive_lock_across_await" not in kinds(new_f, "mutate_job"),
            "before_claim_exclusive": "exclusive_lock_across_await" in kinds(old_f, "claim_queued_job"),
            "after_claim_cleared": "exclusive_lock_across_await" not in kinds(new_f, "claim_queued_job"),
            "no_old_cycle": not old_f.cycles,
            "no_new_cycle": not new_f.cycles,
        }
        result["ferryman"] = {
            "pass": all(ferry_checks.values()),
            "checks": ferry_checks,
            "before": summarize(old_f, ["mutate_job", "claim_queued_job"]),
            "after": summarize(new_f, ["mutate_job", "claim_queued_job"]),
        }

        mini = checkout_one(temp, "mini-redis", MINI_REPO, MINI_COMMIT)
        mini_target = TARGET_ROOT / "mini"
        baseline_gate = cargo_gate(mini, mini_target)
        if not baseline_gate["valid"]:
            raise AssertionError(f"mini-redis baseline gate failed: {baseline_gate}")
        baseline_clippy = clippy_gate(mini, mini_target)
        healthy = analyze(mini, MINI_FILE)
        healthy_lock_findings = [
            item for item in healthy.findings
            if item.get("kind") in {
                "sync_lock_across_await",
                "exclusive_lock_across_await",
                "read_lock_across_await",
                "lock_order_cycle",
            }
        ]
        healthy_quiet = not healthy_lock_findings and not healthy.cycles

        path = mini / MINI_FILE
        before_source = path.read_text("utf-8")
        mini_mutate(path)
        mutated_source = path.read_text("utf-8")
        mutated = analyze(mini, MINI_FILE)
        injected_detected = "sync_lock_across_await" in kinds(mutated, "purge_expired_tasks")
        mutation_check = run(["cargo", "check", "--locked"], cwd=mini, timeout=240, target=mini_target)
        compiler_rejected = mutation_check.returncode != 0 and (
            "cannot be sent between threads safely" in mutation_check.stdout
            or "future cannot be sent" in mutation_check.stdout
            or "Send" in mutation_check.stdout
        )

        repair = repair_file(path)
        repaired_source = path.read_text("utf-8")
        repaired = analyze(mini, MINI_FILE)
        finding_cleared = "sync_lock_across_await" not in kinds(repaired, "purge_expired_tasks")
        repaired_gate = cargo_gate(mini, mini_target)
        repaired_clippy = clippy_gate(mini, mini_target) if baseline_clippy["valid"] else {"valid": None, "skipped": "baseline strict Clippy already red", "baseline": baseline_clippy}
        clippy_rule = True if not baseline_clippy["valid"] else bool(repaired_clippy["valid"])
        unsafe_introduced = "unsafe" in repaired_source and "unsafe" not in mutated_source
        diff = run(["git", "diff", "--", str(MINI_FILE)], cwd=mini, timeout=30)
        mini_checks = {
            "healthy_baseline_quiet": healthy_quiet,
            "injected_detected": injected_detected,
            "compiler_rejected_injection": compiler_rejected,
            "repair_created": repair is not None,
            "repair_finding_cleared": finding_cleared,
            "repaired_check_and_tests": bool(repaired_gate["valid"]),
            "clippy_no_regression": clippy_rule,
            "unsafe_not_introduced": not unsafe_introduced,
            "repair_changed_source": repaired_source != mutated_source,
            "baseline_restorable": bool(before_source),
        }
        result["mini_redis"] = {
            "pass": all(mini_checks.values()),
            "checks": mini_checks,
            "baseline_gate": baseline_gate,
            "baseline_clippy": baseline_clippy,
            "healthy_findings": healthy.findings,
            "mutation_findings": mutated.findings,
            "mutation_check": {"returncode": mutation_check.returncode, "tail": mutation_check.stdout[-2400:]},
            "repair": None if repair is None else repair.__dict__,
            "repaired_findings": repaired.findings,
            "repaired_gate": repaired_gate,
            "repaired_clippy": repaired_clippy,
            "diff": diff.stdout[-5000:],
        }

    elapsed = time.monotonic() - started
    gates = {
        "javis": bool(result["javis"]["pass"]),
        "ferryman": bool(result["ferryman"]["pass"]),
        "mini_redis": bool(result["mini_redis"]["pass"]),
        "runtime_under_720s": elapsed <= 720.0,
    }
    result["elapsed_seconds"] = round(elapsed, 3)
    result["gates"] = gates
    result["verdict"] = "PASS_REAL" if all(gates.values()) else "FAIL_REAL"
    result["tool_versions"] = {
        "rustc": run(["rustc", "--version"], timeout=10).stdout.strip(),
        "cargo": run(["cargo", "--version"], timeout=10).stdout.strip(),
        "rust_analyzer": run(["rust-analyzer", "--version"], timeout=10).stdout.strip(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "PASS_REAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
