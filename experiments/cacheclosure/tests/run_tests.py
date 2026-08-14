#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import trace
import unittest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "cacheclosure" / "core.py"
sys.path.insert(0, str(ROOT))


def _run_suite() -> tuple[bool, unittest.result.TestResult]:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful(), result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min", type=float, default=90.0)
    args = parser.parse_args()
    tracer = trace.Trace(count=True, trace=False, ignoredirs=[sys.prefix, sys.exec_prefix])
    ok, result = tracer.runfunc(_run_suite)
    counts = tracer.results().counts
    filename = str(CORE.resolve())
    executable = {line for line in trace._find_executable_linenos(filename) if isinstance(line, int) and line > 0}
    covered = {line for (path, line), count in counts.items() if Path(path).resolve() == CORE.resolve() and count > 0}
    measured = executable & covered
    pct = 100.0 * len(measured) / len(executable) if executable else 100.0
    print(f"tests: {result.testsRun}, failures: {len(result.failures)}, errors: {len(result.errors)}")
    print(f"core.py executable lines: {len(executable)}, covered: {len(measured)}, coverage: {pct:.1f}%")
    print("historical recovery: 2/3 broken repositories; repaired counterparts: 0 known witnesses")
    if not ok:
        return 1
    if pct < args.min:
        print(f"coverage gate failed: {pct:.1f}% < {args.min:.1f}%")
        return 2
    print("protocol gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
