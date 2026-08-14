#!/usr/bin/env python3
"""Real-repository runner amendment A1: semantic evidence collection only.

Historical commits, expected transitions, repair mutation, cargo gates, Clippy
policy, and the 12-minute budget are unchanged.
"""
import run_pro_real as base
import semantic_probe_v2 as semantic

base.SemanticLockScope = semantic.SemanticLockScope
base.finding_kinds = semantic.finding_kinds

if __name__ == "__main__":
    raise SystemExit(base.main())
