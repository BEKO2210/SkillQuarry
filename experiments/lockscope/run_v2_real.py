#!/usr/bin/env python3
"""LockScope v2 real-repository runner using structured syntax extraction."""
import run_pro_real as base
import semantic_probe_v3 as semantic

base.SemanticLockScope = semantic.SemanticLockScope
base.finding_kinds = semantic.finding_kinds

if __name__ == "__main__":
    raise SystemExit(base.main())
