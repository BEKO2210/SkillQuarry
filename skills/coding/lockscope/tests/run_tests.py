#!/usr/bin/env python3
"""Run the LockScope suites and report what actually ran.

    python3 tests/run_tests.py                  everything this machine can run
    python3 tests/run_tests.py --structural     no Rust toolchain needed
    python3 tests/run_tests.py --real           add the real-repository suite
    python3 tests/run_tests.py --min 90         fail if fewer tests ran

The count of skipped suites is printed on purpose: a run that quietly skipped
the semantic half looks exactly like a run that passed it, and that is worth
being loud about. In CI, `LOCKSCOPE_REQUIRE_TOOLCHAIN=1` turns a skip into a
failure.
"""
from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

import harness  # noqa: E402

STRUCTURAL = ["test_syntax", "test_engine", "test_repair", "test_report", "test_cli"]
TOOLCHAIN = ["test_semantic", "test_compiler", "test_repair_proof"]
REAL = ["test_real_repos"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--structural", action="store_true", help="only the suites that need no Rust")
    parser.add_argument("--real", action="store_true", help="include the real-repository suite")
    parser.add_argument("--only", action="append", metavar="SUITE",
                        help="run just these suites (repeatable), e.g. --only test_real_repos")
    parser.add_argument("--min", type=int, default=0, help="fail if fewer than this many tests ran")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.only:
        known = set(STRUCTURAL + TOOLCHAIN + REAL)
        unknown = [name for name in args.only if name not in known]
        if unknown:
            print(f"unknown suite(s): {', '.join(unknown)}", file=sys.stderr)
            return 3
        modules = list(args.only)
    else:
        modules = list(STRUCTURAL)
        if not args.structural:
            modules += TOOLCHAIN
        if args.real:
            modules += REAL

    if not harness.parser_available():
        print("tree-sitter and tree-sitter-rust are required; run ./install.sh first", file=sys.stderr)
        return 3

    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in modules)
    runner = unittest.TextTestRunner(verbosity=1 if args.quiet else 2)
    result = runner.run(suite)

    ran = result.testsRun
    skipped = len(result.skipped)
    print()
    print(f"suites   {' '.join(modules)}")
    print(f"ran      {ran} tests, {skipped} skipped, {len(result.failures)} failed, {len(result.errors)} errored")
    if skipped:
        print("skipped because this machine lacks a tool:")
        for case, reason in result.skipped:
            print(f"  {case.id().split('.')[0]:<20} {reason}")
        if os.environ.get("LOCKSCOPE_REQUIRE_TOOLCHAIN") == "1":
            print("LOCKSCOPE_REQUIRE_TOOLCHAIN=1: a skip is a failure here")
            return 1
    if args.min and ran - skipped < args.min:
        print(f"only {ran - skipped} tests ran, at least {args.min} were required")
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
