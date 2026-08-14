#!/usr/bin/env python3
"""Run Cordon tests and enforce stdlib trace line coverage of core.py."""
from __future__ import annotations

import argparse
import sys
import trace
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(TESTS_DIR))
TARGET = SRC_DIR / "cordon" / "core.py"


def executable_lines(path: Path) -> set[int]:
    source = path.read_text("utf-8")
    root = compile(source, str(path), "exec")
    excluded = {n for n, text in enumerate(source.splitlines(), 1) if "pragma: no cover" in text}
    lines: set[int] = set()
    stack = [root]
    while stack:
        code = stack.pop()
        for _start, _end, line in code.co_lines():
            if line:
                lines.add(line)
        stack.extend(item for item in code.co_consts if hasattr(item, "co_lines"))
    return lines - excluded


def run_suite() -> unittest.TestResult:
    suite = unittest.TestLoader().discover(str(TESTS_DIR), pattern="test_*.py", top_level_dir=str(TESTS_DIR))
    return unittest.TextTestRunner(verbosity=2).run(suite)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min", type=float, default=0.0)
    parser.add_argument("--no-coverage", action="store_true")
    ns = parser.parse_args()
    if ns.no_coverage:
        result = run_suite()
        return 0 if result.wasSuccessful() else 1
    tracer = trace.Trace(count=1, trace=0, ignoremods=("trace", "unittest", "runpy"))
    holder: dict[str, unittest.TestResult] = {}
    tracer.runfunc(lambda: holder.update(result=run_suite()))
    result = holder["result"]
    counts = tracer.results().counts
    executed = {line for (path, line) in counts if Path(path).resolve() == TARGET.resolve()}
    executable = executable_lines(TARGET)
    missing = sorted(executable - executed)
    percent = 100.0 * (len(executable) - len(missing)) / len(executable) if executable else 100.0
    print()
    print(f"coverage: core.py {percent:.1f}%  ({len(executable) - len(missing)}/{len(executable)} executable lines)")
    if missing:
        print(f"uncovered lines: {missing}")
    if not result.wasSuccessful():
        return 1
    if percent + 1e-9 < ns.min:
        print(f"FAIL: coverage {percent:.1f}% is below the required {ns.min:.1f}%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
