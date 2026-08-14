"""Independent checks that can overrule a repair.

Nothing here trusts the edit that was just made. `cargo check` and `cargo test`
are run by the compiler, the unsafe delta is counted in the diff, and the
analysis is run again from scratch. A repair that clears a finding but breaks
the build is a failed repair.

Clippy is compared against a baseline instead of being required to be clean: a
pinned third-party repository can carry diagnostics that have nothing to do with
the change, and calling those a regression would be dishonest in both directions.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

UNSAFE = re.compile(rb"\bunsafe\b")


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    passed: bool
    output_tail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run(argv: list[str], cwd: Path, timeout: float = 900.0, env: dict[str, str] | None = None) -> CommandResult:
    try:
        finished = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False, env=env
        )
    except FileNotFoundError:
        return CommandResult(" ".join(argv), 127, False, f"{argv[0]} is not installed")
    except subprocess.TimeoutExpired:
        return CommandResult(" ".join(argv), 124, False, f"timed out after {timeout:.0f}s")
    output = (finished.stdout + finished.stderr).strip()
    return CommandResult(" ".join(argv), finished.returncode, finished.returncode == 0, output[-2000:])


def cargo_check(crate: Path, locked: bool = True) -> CommandResult:
    argv = ["cargo", "check", "--all-targets"] + (["--locked"] if locked else [])
    return run(argv, crate)


def cargo_test(crate: Path, locked: bool = True) -> CommandResult:
    argv = ["cargo", "test"] + (["--locked"] if locked else [])
    return run(argv, crate)


def clippy(crate: Path, locked: bool = True) -> CommandResult:
    argv = ["cargo", "clippy", "--all-targets"] + (["--locked"] if locked else []) + ["--", "-D", "warnings"]
    return run(argv, crate)


def clippy_regression(before: CommandResult, after: CommandResult) -> dict[str, Any]:
    """Whether Clippy got worse, measured against the baseline it started at.

    A repository that was already red stays red without that counting against
    the repair; a repository that was green and is now red does count.
    """
    regressed = bool(before.passed and not after.passed)
    return {
        "baseline_passed": before.passed,
        "after_passed": after.passed,
        "regressed": regressed,
        "note": (
            "baseline already failed; comparison is baseline-relative"
            if not before.passed else "baseline was clean"
        ),
    }


def unsafe_count(paths: list[Path]) -> int:
    """Occurrences of the `unsafe` keyword across the given files."""
    total = 0
    for path in paths:
        try:
            total += len(UNSAFE.findall(path.read_bytes()))
        except OSError:
            continue
    return total


def unsafe_delta(before: int, after: int) -> dict[str, Any]:
    return {"before": before, "after": after, "delta": after - before, "introduced": after > before}


def spawn_send_probe(crate: Path, source: str, name: str = "lockscope_send_probe") -> CommandResult:
    """Ask the compiler whether a future is `Send`, instead of assuming it.

    The probe is written into the crate as a test target and compiled. Whether
    `rustc` accepts it is the ground truth about guard lifetimes — folklore
    about `drop()` does not survive contact with this.
    """
    target = crate / "tests" / f"{name}.rs"
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    previous = target.read_bytes() if existed else None
    target.write_text(source, "utf-8")
    try:
        return run(["cargo", "check", "--test", name], crate)
    finally:
        if previous is not None:
            target.write_bytes(previous)
        else:
            target.unlink(missing_ok=True)
