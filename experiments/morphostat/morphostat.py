#!/usr/bin/env python3
"""Minimal target-morphology detector for the Morphostat concept test.

This prototype intentionally models only structural invariants that can be
reproduced without third-party packages: required Rust modules, allowed
inter-module dependencies, and selected public API signatures.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CRATE_REF = re.compile(r"\bcrate::([A-Za-z_][A-Za-z0-9_]*)")
PUBLIC_ITEM = re.compile(r"^\s*pub\s+(?:async\s+)?(?:unsafe\s+)?fn\s+[^\{;]+")


def normalize_signature(line: str) -> str:
    signature = line.strip()
    if "{" in signature:
        signature = signature.split("{", 1)[0].rstrip()
    return " ".join(signature.split())


def discover_modules(src_dir: Path) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in sorted(src_dir.glob("*.rs")):
        if path.name == "lib.rs":
            continue
        modules[path.stem] = path
    return modules


def dependencies_for(path: Path, known_modules: set[str]) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {
        match.group(1)
        for match in CRATE_REF.finditer(text)
        if match.group(1) in known_modules and match.group(1) != path.stem
    }


def public_signatures(path: Path) -> set[str]:
    signatures: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if PUBLIC_ITEM.match(line):
            signatures.add(normalize_signature(line))
    return signatures


def evaluate(root: Path, spec: dict) -> dict:
    src_dir = root / "src"
    modules = discover_modules(src_dir)
    known = set(modules)
    violations: list[dict[str, str]] = []

    required_modules = set(spec.get("required_modules", []))
    for missing in sorted(required_modules - known):
        violations.append(
            {
                "kind": "missing_module",
                "subject": missing,
                "detail": f"required module {missing!r} is absent",
            }
        )

    allowed = {
        module: set(targets)
        for module, targets in spec.get("allowed_dependencies", {}).items()
    }
    dependency_snapshot: dict[str, list[str]] = {}
    for module, path in sorted(modules.items()):
        actual = dependencies_for(path, known)
        dependency_snapshot[module] = sorted(actual)
        permitted = allowed.get(module, set())
        for target in sorted(actual - permitted):
            violations.append(
                {
                    "kind": "forbidden_dependency",
                    "subject": f"{module}->{target}",
                    "detail": f"{module!r} depends on {target!r}, outside its target morphology",
                }
            )

    api_snapshot: dict[str, list[str]] = {}
    for module, expected in sorted(spec.get("public_api", {}).items()):
        path = modules.get(module)
        if path is None:
            continue
        actual = public_signatures(path)
        api_snapshot[module] = sorted(actual)
        for required_signature in expected:
            normalized = normalize_signature(required_signature)
            if normalized not in actual:
                violations.append(
                    {
                        "kind": "public_api_drift",
                        "subject": module,
                        "detail": f"missing target signature: {normalized}",
                    }
                )

    return {
        "healthy": not violations,
        "violations": violations,
        "snapshot": {
            "modules": sorted(known),
            "dependencies": dependency_snapshot,
            "public_api": api_snapshot,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        result = evaluate(args.root, spec)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["healthy"] else 2


if __name__ == "__main__":
    sys.exit(main())
