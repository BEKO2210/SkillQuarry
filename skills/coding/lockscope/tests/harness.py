"""Shared helpers for the LockScope suites.

Two kinds of test live side by side here. The structural ones need nothing but
the Rust grammar and run in under a second; the semantic, compiler and
real-repository ones need rust-analyzer, cargo and a linker. The second kind is
skipped when the machine cannot run it and *fails* when the environment claims it
can — a suite that quietly skips its hardest half is how a green run stops
meaning anything.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURES = ROOT / "fixtures"
CASES = FIXTURES / "cases"
CONTENTION = FIXTURES / "contention"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Set this in CI so a missing toolchain is a failure rather than a silent skip.
STRICT = os.environ.get("LOCKSCOPE_REQUIRE_TOOLCHAIN") == "1"


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


def _has_linker() -> bool:
    return _has("cc") or _has("gcc") or _has("clang")


def missing_tools(*, rust_analyzer: bool = False, cargo: bool = False) -> list[str]:
    """What this machine lacks for the requested kind of test.

    Semantic resolution and compilation are separate needs. rust-analyzer
    answers type questions from `cargo metadata` and the sources, which works on
    a machine with no C linker at all; only the suites that actually build
    something need one. Conflating the two would skip the semantic suite on
    perfectly capable machines.
    """
    missing = []
    if cargo:
        if not _has("cargo"):
            missing.append("cargo")
        if not _has("rustc"):
            missing.append("rustc")
        if not _has_linker():
            missing.append("cc (a C linker; cargo cannot link without one)")
    if rust_analyzer:
        if not _has("rust-analyzer"):
            missing.append("rust-analyzer")
        if not _has("cargo"):
            missing.append("cargo (rust-analyzer needs `cargo metadata`)")
    return missing


def require(*, rust_analyzer: bool = False, cargo: bool = False) -> None:
    """Skip when the machine cannot run this, unless CI says it must."""
    missing = missing_tools(rust_analyzer=rust_analyzer, cargo=cargo)
    if not missing:
        return
    message = "missing: " + ", ".join(missing)
    if STRICT:
        raise AssertionError(
            f"LOCKSCOPE_REQUIRE_TOOLCHAIN=1 but {message}. "
            "This environment claimed it could run the full suite."
        )
    raise unittest.SkipTest(message)


def parser_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_rust  # noqa: F401
    except Exception:
        return False
    return True


def run(argv: list[str], cwd: Path, timeout: float = 900.0) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)


def source(text: str) -> bytes:
    """Fixture source written inline, with the leading newline removed."""
    return text.lstrip("\n").encode("utf-8")


class TempCrate:
    """A copy of a fixture crate that a test may modify freely."""

    def __init__(self, original: Path, destination: Path):
        self.original = original
        self.path = destination

    def __enter__(self) -> Path:
        shutil.copytree(self.original, self.path, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("target"))
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
