#!/usr/bin/env python3

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import redteam as rt
import pro_test as p

NIGHTLY = "nightly-2026-08-13"


def run_json(root: Path, args: list[str], target_dir: Path) -> dict:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    completed = subprocess.run(
        args,
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\nstdout:\n{completed.stdout[-2000:]}\nstderr:\n{completed.stderr[-2000:]}"
        )
    return json.loads(completed.stdout)


def metadata_signature(root: Path, target_dir: Path) -> dict:
    data = run_json(
        root,
        ["cargo", "metadata", "--format-version", "1", "--no-deps"],
        target_dir,
    )
    packages = {}
    for package in data["packages"]:
        dependencies = []
        for dep in package.get("dependencies", []):
            dependencies.append(
                {
                    "name": dep.get("name"),
                    "rename": dep.get("rename"),
                    "kind": dep.get("kind"),
                    "target": dep.get("target"),
                    "optional": dep.get("optional"),
                    "features": dep.get("features", []),
                    "uses_default_features": dep.get("uses_default_features"),
                }
            )
        packages[package["name"]] = {
            "dependencies": sorted(
                dependencies,
                key=lambda item: json.dumps(item, sort_keys=True),
            ),
            "features": package.get("features", {}),
            "targets": sorted(
                (
                    {
                        "name": target.get("name"),
                        "kind": target.get("kind"),
                        "crate_types": target.get("crate_types"),
                    }
                    for target in package.get("targets", [])
                ),
                key=lambda item: json.dumps(item, sort_keys=True),
            ),
        }
    return dict(sorted(packages.items()))


def rustdoc_blob(root: Path, package: str, target_dir: Path) -> dict:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    completed = subprocess.run(
        [
            "cargo",
            f"+{NIGHTLY}",
            "rustdoc",
            "-p",
            package,
            "--lib",
            "-Z",
            "unstable-options",
            "--output-format",
            "json",
        ],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"rustdoc failed for {package}:\n{completed.stdout[-4000:]}"
        )
    expected = target_dir / "doc" / f"{package.replace('-', '_')}.json"
    if not expected.is_file():
        candidates = sorted((target_dir / "doc").glob("*.json"))
        raise RuntimeError(
            f"rustdoc JSON not found at {expected}; candidates={candidates}"
        )
    return json.loads(expected.read_text(encoding="utf-8"))


def clean_semantic(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            if key in {
                "id",
                "crate_id",
                "span",
                "docs",
                "links",
                "attrs",
                "deprecation",
                "stability",
                "const_stability",
            }:
                continue
            cleaned[key] = clean_semantic(child)
        return cleaned
    if isinstance(value, list):
        return [clean_semantic(item) for item in value]
    return value


def public_semantic_signature(blob: dict) -> str:
    # rustdoc JSON with private items disabled is the compiler-produced public/reachable
    # documentation graph. Remove source-location/documentation noise, then hash the
    # remaining semantic graph. Opaque references are retained because they connect
    # signatures to their compiler-resolved items.
    payload = {
        "includes_private": blob.get("includes_private"),
        "index": clean_semantic(blob.get("index", {})),
        "root": blob.get("root"),
        "target": clean_semantic(blob.get("target", {})),
        "format_version": blob.get("format_version"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def make_pair(arena: Path, name: str, setup, mutate) -> tuple[Path, Path]:
    healthy = arena / f"{name}-healthy"
    healthy.mkdir(parents=True)
    p.write_workspace(healthy)
    if setup:
        setup(healthy)
    actual = arena / f"{name}-actual"
    shutil.copytree(healthy, actual)
    mutate(actual)
    return healthy, actual


def main() -> int:
    results = []
    failures = []
    with tempfile.TemporaryDirectory(prefix="morphostat-native-") as tmp:
        arena = Path(tmp)

        # Cargo owns dependency semantics. This case escaped the prototype because
        # it lived in a target-specific dependency table.
        healthy, actual = make_pair(
            arena,
            "target-specific-dependency",
            None,
            rt.target_specific_dependency,
        )
        meta_healthy = metadata_signature(healthy, arena / "meta-healthy")
        meta_actual = metadata_signature(actual, arena / "meta-actual")
        metadata_detected = meta_healthy != meta_actual
        app_targets = [
            dep.get("target")
            for dep in meta_actual["app"]["dependencies"]
            if dep.get("name") == "storage"
        ]
        target_preserved = "cfg(unix)" in app_targets
        results.append(
            {
                "case": "target_specific_dependency",
                "source": "cargo_metadata",
                "detected": metadata_detected,
                "target_preserved": target_preserved,
            }
        )
        if not (metadata_detected and target_preserved):
            failures.append("cargo metadata did not preserve target-specific dependency semantics")

        api_cases = [
            ("trait_method_signature_drift", rt.setup_trait, rt.mutate_trait, "domain"),
            ("public_struct_field_type_drift", rt.setup_public_struct, rt.mutate_public_struct, "domain"),
            ("macro_generated_public_api_drift", rt.setup_macro_api, rt.mutate_macro_api, "app"),
            ("multiline_public_signature_drift", rt.setup_multiline_signature, rt.mutate_multiline_signature, "app"),
        ]
        for index, (name, setup, mutate, package) in enumerate(api_cases):
            healthy, actual = make_pair(arena, name, setup, mutate)
            healthy_blob = rustdoc_blob(
                healthy,
                package,
                arena / f"rustdoc-{index}-healthy",
            )
            actual_blob = rustdoc_blob(
                actual,
                package,
                arena / f"rustdoc-{index}-actual",
            )
            healthy_sig = public_semantic_signature(healthy_blob)
            actual_sig = public_semantic_signature(actual_blob)
            detected = healthy_sig != actual_sig
            results.append(
                {
                    "case": name,
                    "source": "rustdoc_json",
                    "detected": detected,
                    "healthy_format_version": healthy_blob.get("format_version"),
                    "actual_format_version": actual_blob.get("format_version"),
                }
            )
            if not detected:
                failures.append(f"rustdoc JSON did not expose {name}")

        # Negative control: a private implementation-only helper must not perturb
        # the compiler-derived public API signature.
        healthy, actual = make_pair(
            arena,
            "private-helper-control",
            None,
            p.c_private_helper,
        )
        healthy_blob = rustdoc_blob(
            healthy,
            "service",
            arena / "control-healthy",
        )
        actual_blob = rustdoc_blob(
            actual,
            "service",
            arena / "control-actual",
        )
        changed = public_semantic_signature(healthy_blob) != public_semantic_signature(actual_blob)
        results.append(
            {
                "case": "private_helper_control",
                "source": "rustdoc_json",
                "detected": changed,
                "expected_detected": False,
            }
        )
        if changed:
            failures.append("rustdoc semantic fingerprint changed for private-only helper refactor")

    summary = {
        "failures": failures,
        "cases": len(results),
        "positive_cases": 5,
        "negative_controls": 1,
        "results": results,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
