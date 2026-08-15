#!/usr/bin/env python3
"""Compatibility launcher for the frozen unseen holdout.

This file does not change the detector, fixture, witness, run count, or gates.
It only materializes pyc's declared generated check_cast.cc build prerequisite
before the historical snapshot's incomplete dependency graph is built.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
TARGET = HERE / "holdout.py"

spec = importlib.util.spec_from_file_location("frozen_build_entropy_holdout", TARGET)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load frozen runner: {TARGET}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

frozen_probe_pyc = mod.probe_pyc


def compatible_probe_pyc(repo: Path):
    # Historical ifa/Makefile declares this generator target, while num.o in
    # the pinned snapshot does not declare the generated include dependency.
    # Generate exactly that build artifact first; do not patch target source.
    mod.run(["make", "-C", "ifa", "if1/check_cast.cc"], cwd=repo, timeout=300)
    return frozen_probe_pyc(repo)


mod.probe_pyc = compatible_probe_pyc
mod.PROBERS["pyc"] = compatible_probe_pyc

if __name__ == "__main__":
    raise SystemExit(mod.main())
