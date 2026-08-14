#!/usr/bin/env python3

import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import compiler_native_feasibility as native
import lsp_semantic_feasibility as lsp

UPSTREAM_URL = "https://github.com/BurntSushi/ripgrep.git"
UPSTREAM_SHA = "3fce3b5bb0236da2df6d99672afb8a719642eca7"
NIGHTLY = "nightly-2026-08-13"
MOD_DECL = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", re.MULTILINE)


def run(args, cwd, *, env=None, timeout=300, check=True):
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(args)}\n"
            f"stdout:\n{completed.stdout[-4000:]}\n"
            f"stderr:\n{completed.stderr[-4000:]}"
        )
    return completed


def clone_upstream(root: Path) -> Path:
    repo = root / "ripgrep"
    repo.mkdir()
    run(["git", "init", "-q"], repo)
    run(["git", "remote", "add", "origin", UPSTREAM_URL], repo)
    run(["git", "fetch", "--depth=1", "origin", UPSTREAM_SHA], repo, timeout=180)
    run(["git", "checkout", "--detach", "-q", "FETCH_HEAD"], repo)
    actual = run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    if actual != UPSTREAM_SHA:
        raise RuntimeError(f"upstream pin mismatch: {actual}")
    return repo


def reset_repo(repo: Path) -> None:
    run(["git", "reset", "--hard", "-q", UPSTREAM_SHA], repo)
    run(["git", "clean", "-fdq"], repo)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one occurrence in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def cargo_env(target_dir: Path) -> dict:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    env["CARGO_TERM_COLOR"] = "never"
    return env


def standard_gate(repo: Path, target_dir: Path) -> dict:
    env = cargo_env(target_dir)
    commands = [
        ("check", ["cargo", "check", "--workspace", "--lib", "--bins", "--tests"]),
        ("clippy", ["cargo", "clippy", "-p", "ignore", "--all-targets", "--", "-D", "warnings"]),
        ("test", ["cargo", "test", "-p", "ignore", "--quiet"]),
    ]
    evidence = {}
    for name, args in commands:
        started = time.monotonic()
        completed = run(args, repo, env=env, timeout=420, check=False)
        evidence[name] = {
            "pass": completed.returncode == 0,
            "seconds": round(time.monotonic() - started, 3),
            "tail": (completed.stdout + completed.stderr)[-1200:],
        }
        if completed.returncode != 0:
            return {"pass": False, "failed_stage": name, "evidence": evidence}
    return {"pass": True, "failed_stage": None, "evidence": evidence}


def metadata_signature(repo: Path, target_dir: Path) -> dict:
    env = cargo_env(target_dir)
    completed = run(
        ["cargo", "metadata", "--format-version", "1", "--no-deps"],
        repo,
        env=env,
        timeout=180,
    )
    data = json.loads(completed.stdout)
    id_to_name = {package["id"]: package["name"] for package in data["packages"]}
    packages = {}
    for package in data["packages"]:
        dependencies = []
        for dep in package.get("dependencies", []):
            dependencies.append(
                {
                    "name": dep.get("name"),
                    "rename": dep.get("rename"),
                    "req": dep.get("req"),
                    "kind": dep.get("kind"),
                    "target": dep.get("target"),
                    "optional": dep.get("optional"),
                    "features": dep.get("features", []),
                    "uses_default_features": dep.get("uses_default_features"),
                }
            )
        packages[package["name"]] = {
            "version": package.get("version"),
            "dependencies": sorted(dependencies, key=lambda item: json.dumps(item, sort_keys=True)),
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
    members = sorted(id_to_name.get(member, member) for member in data.get("workspace_members", []))
    return {"workspace_members": members, "packages": dict(sorted(packages.items()))}


def rustdoc_api_hash(repo: Path, target_dir: Path) -> tuple[str, int]:
    blob = native.rustdoc_blob(repo, "ignore", target_dir)
    return native.public_semantic_signature(blob), int(blob.get("format_version", -1))


def module_name(path: Path, src: Path) -> str:
    rel = path.resolve().relative_to(src.resolve())
    if rel.name == "lib.rs":
        return "__root__"
    if rel.name == "mod.rs":
        rel = rel.parent
    else:
        rel = rel.with_suffix("")
    return "::".join(rel.parts)


def location_path(result):
    return lsp.location_path(result)


def scan_overrides_edges(client: lsp.LspClient, path: Path, src: Path) -> list[str]:
    edges = set()
    text = path.read_text(encoding="utf-8")
    origin = module_name(path, src)
    for line_no, line in enumerate(text.splitlines()):
        for match in lsp.IDENT.finditer(line):
            target_path = location_path(client.definition(path, line_no, match.start()))
            if target_path is None or not target_path.is_relative_to(src.resolve()):
                continue
            target = module_name(target_path, src)
            if target != origin and target != "__root__":
                edges.add(f"{origin}->{target}")
    return sorted(edges)


def semantic_overrides_edges(repo: Path) -> list[str]:
    src = (repo / "crates/ignore/src").resolve()
    files = sorted(src.rglob("*.rs"))
    overrides = src / "overrides.rs"
    client = lsp.LspClient(repo)
    try:
        for path in files:
            client.open_document(path)
        text = overrides.read_text(encoding="utf-8")
        marker = text.find("Gitignore")
        if marker < 0:
            raise RuntimeError("known readiness marker Gitignore not found")
        prefix = text[:marker]
        line = prefix.count("\n")
        char = len(prefix.rsplit("\n", 1)[-1])
        deadline = time.monotonic() + 20.0
        while True:
            target = location_path(client.definition(overrides, line, char))
            if target is not None and target.name == "gitignore.rs":
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("rust-analyzer did not become semantically ready")
            time.sleep(0.2)
        return scan_overrides_edges(client, overrides, src)
    finally:
        client.close()


def extract_morphology(repo: Path, target_dir: Path) -> tuple[dict, float]:
    started = time.monotonic()
    metadata = metadata_signature(repo, target_dir)
    api_hash, format_version = rustdoc_api_hash(repo, target_dir)
    edges = semantic_overrides_edges(repo)
    morphology = {
        "source": {"repository": "BurntSushi/ripgrep", "commit": UPSTREAM_SHA},
        "metadata": metadata,
        "ignore_public_api": {"sha256": api_hash, "rustdoc_format_version": format_version},
        "ignore_overrides_semantic_edges": edges,
    }
    return morphology, time.monotonic() - started


def morphology_diffs(baseline: dict, actual: dict) -> list[str]:
    diffs = []
    if baseline["metadata"] != actual["metadata"]:
        diffs.append("cargo_metadata")
    if baseline["ignore_public_api"] != actual["ignore_public_api"]:
        diffs.append("rustdoc_public_api")
    if baseline["ignore_overrides_semantic_edges"] != actual["ignore_overrides_semantic_edges"]:
        diffs.append("rust_analyzer_internal_edges")
    return diffs


def scoped_source_bytes(repo: Path) -> int:
    paths = list(repo.rglob("Cargo.toml")) + list((repo / "crates/ignore/src").rglob("*.rs"))
    return sum(path.stat().st_size for path in paths if ".git" not in path.parts)


def m_feature_added(repo: Path) -> None:
    append(repo / "crates/ignore/Cargo.toml", "\nmorphostat-probe = []\n")


def m_default_feature_added(repo: Path) -> None:
    replace_once(
        repo / "crates/ignore/Cargo.toml",
        "[features]\n",
        "[features]\ndefault = [\"simd-accel\"]\n",
    )


def m_optional_dependency(repo: Path) -> None:
    replace_once(
        repo / "crates/ignore/Cargo.toml",
        "[dependencies.regex-automata]",
        "morphostat_probe_dep = { package = \"grep-matcher\", path = \"../matcher\", optional = true }\n\n[dependencies.regex-automata]",
    )


def m_target_dependency(repo: Path) -> None:
    append(
        repo / "crates/ignore/Cargo.toml",
        "\n[target.'cfg(target_os = \"none\")'.dependencies]\n"
        "morphostat_probe_dep = { package = \"grep-matcher\", path = \"../matcher\" }\n",
    )


def m_workspace_member(repo: Path) -> None:
    replace_once(
        repo / "Cargo.toml",
        '  "crates/ignore",\n',
        '  "crates/ignore",\n  "crates/morphostat-probe",\n',
    )
    write(
        repo / "crates/morphostat-probe/Cargo.toml",
        "[package]\nname = \"morphostat-probe\"\nversion = \"0.1.0\"\nedition = \"2024\"\npublish = false\n",
    )
    write(repo / "crates/morphostat-probe/src/lib.rs", "pub fn marker() -> u8 { 1 }\n")


def m_package_version(repo: Path) -> None:
    replace_once(repo / "crates/ignore/Cargo.toml", 'version = "0.4.33"', 'version = "0.4.34"')


def m_public_alias(repo: Path) -> None:
    marker = "mod walk;\n"
    replace_once(
        repo / "crates/ignore/src/lib.rs",
        marker,
        marker + "\n/// Public probe used only by the Morphostat evaluation.\npub type MorphostatPublicProbe = usize;\n",
    )


def m_public_reexport(repo: Path) -> None:
    marker = "pub use crate::walk::{\n"
    replace_once(
        repo / "crates/ignore/src/lib.rs",
        marker,
        "pub use crate::types::Types as MorphostatTypesProbe;\n" + marker,
    )


def add_types_marker(repo: Path) -> None:
    path = repo / "crates/ignore/src/types.rs"
    text = path.read_text(encoding="utf-8")
    path.write_text("pub(crate) const MORPHOSTAT_MARKER: () = ();\n\n" + text, encoding="utf-8")


def m_direct_internal_edge(repo: Path) -> None:
    add_types_marker(repo)
    replace_once(
        repo / "crates/ignore/src/overrides.rs",
        "    pub fn empty() -> Override {\n        Override(Gitignore::empty())",
        "    pub fn empty() -> Override {\n        let _ = crate::types::MORPHOSTAT_MARKER;\n        Override(Gitignore::empty())",
    )


def m_alias_internal_edge(repo: Path) -> None:
    add_types_marker(repo)
    replace_once(
        repo / "crates/ignore/src/overrides.rs",
        "use std::path::Path;\n",
        "use std::path::Path;\nuse crate as morph_root;\n",
    )
    replace_once(
        repo / "crates/ignore/src/overrides.rs",
        "    pub fn empty() -> Override {\n        Override(Gitignore::empty())",
        "    pub fn empty() -> Override {\n        let _ = morph_root::types::MORPHOSTAT_MARKER;\n        Override(Gitignore::empty())",
    )


def m_dependency_requirement(repo: Path) -> None:
    replace_once(
        repo / "crates/ignore/Cargo.toml",
        'memchr = "2.6.3"',
        'memchr = ">=2.6.3, <3"',
    )


def c_comment_only(repo: Path) -> None:
    append(repo / "crates/ignore/src/overrides.rs", "\n// Morphostat control: comment only.\n")


def c_docs_only(repo: Path) -> None:
    replace_once(
        repo / "crates/ignore/src/overrides.rs",
        "/// Returns an empty matcher that never matches any file path.",
        "/// Returns an empty matcher that never matches any file path.\n    /// Documentation-only Morphostat control.",
    )


def c_private_helper(repo: Path) -> None:
    replace_once(
        repo / "crates/ignore/src/overrides.rs",
        "impl Override {\n",
        "impl Override {\n    fn morphostat_identity(value: bool) -> bool { value }\n\n",
    )
    replace_once(
        repo / "crates/ignore/src/overrides.rs",
        "    pub fn is_empty(&self) -> bool {\n        self.0.is_empty()",
        "    pub fn is_empty(&self) -> bool {\n        Self::morphostat_identity(self.0.is_empty())",
    )


def c_whitespace(repo: Path) -> None:
    path = repo / "crates/ignore/src/overrides.rs"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("use std::path::Path;", "use std::path::Path;\n"), encoding="utf-8")


def c_behavior_bug(repo: Path) -> None:
    replace_once(
        repo / "crates/ignore/src/overrides.rs",
        "        let mat = self.0.matched(path, is_dir).invert();",
        "        let mat = self.0.matched(path, is_dir);",
    )


POSITIVES = [
    ("feature_added", m_feature_added, "cargo_metadata"),
    ("default_feature_added", m_default_feature_added, "cargo_metadata"),
    ("optional_dependency_added", m_optional_dependency, "cargo_metadata"),
    ("target_specific_dependency_added", m_target_dependency, "cargo_metadata"),
    ("workspace_member_added", m_workspace_member, "cargo_metadata"),
    ("package_version_drift", m_package_version, "cargo_metadata"),
    ("dependency_requirement_drift", m_dependency_requirement, "cargo_metadata"),
    ("public_type_alias_added", m_public_alias, "rustdoc_public_api"),
    ("public_reexport_added", m_public_reexport, "rustdoc_public_api"),
    ("direct_internal_edge", m_direct_internal_edge, "rust_analyzer_internal_edges"),
    ("alias_internal_edge", m_alias_internal_edge, "rust_analyzer_internal_edges"),
]

CONTROLS = [
    ("comment_only", c_comment_only, True),
    ("docs_only", c_docs_only, True),
    ("private_helper_same_module", c_private_helper, True),
    ("whitespace_only", c_whitespace, True),
    ("behavior_only_bug", c_behavior_bug, False),
]


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="morphostat-realworld-") as tmp:
        arena = Path(tmp)
        repo = clone_upstream(arena)
        target_dir = arena / "cargo-target"

        baseline_gate = standard_gate(repo, target_dir)
        if not baseline_gate["pass"]:
            print(json.dumps({"fatal": "pinned upstream baseline failed standard gate", "gate": baseline_gate}, indent=2))
            return 2

        baseline_runs = []
        baseline_times = []
        for _ in range(3):
            morphology, seconds = extract_morphology(repo, target_dir)
            baseline_runs.append(morphology)
            baseline_times.append(seconds)
        deterministic = baseline_runs[0] == baseline_runs[1] == baseline_runs[2]
        if not deterministic:
            failures.append("baseline morphology was not deterministic across three unchanged extractions")
        baseline = baseline_runs[0]

        results = []
        extraction_times = list(baseline_times)
        standard_detected = 0
        additional_while_standard_green = 0
        detected_positives = 0

        for name, mutate, expected_sensor in POSITIVES:
            reset_repo(repo)
            mutate(repo)
            gate = standard_gate(repo, target_dir)
            actual, seconds = extract_morphology(repo, target_dir)
            extraction_times.append(seconds)
            diffs = morphology_diffs(baseline, actual)
            detected = bool(diffs)
            sensor_correct = expected_sensor in diffs
            if detected:
                detected_positives += 1
            if not gate["pass"]:
                standard_detected += 1
            elif detected:
                additional_while_standard_green += 1
            if not detected:
                failures.append(f"false negative: {name}")
            if not sensor_correct:
                failures.append(f"wrong/missing sensor for {name}: expected {expected_sensor}, got {diffs}")
            results.append(
                {
                    "name": name,
                    "kind": "structural",
                    "expected_sensor": expected_sensor,
                    "morphostat_detected": detected,
                    "sensor_diffs": diffs,
                    "standard_rust_pass": gate["pass"],
                    "standard_failed_stage": gate["failed_stage"],
                    "extraction_seconds": round(seconds, 3),
                }
            )

        false_positives = 0
        behavior_control_ok = False
        for name, mutate, expect_standard_pass in CONTROLS:
            reset_repo(repo)
            mutate(repo)
            gate = standard_gate(repo, target_dir)
            actual, seconds = extract_morphology(repo, target_dir)
            extraction_times.append(seconds)
            diffs = morphology_diffs(baseline, actual)
            detected = bool(diffs)
            if detected:
                false_positives += 1
                failures.append(f"false positive control: {name} -> {diffs}")
            if expect_standard_pass and not gate["pass"]:
                failures.append(f"control unexpectedly failed standard Rust gate: {name}/{gate['failed_stage']}")
            if not expect_standard_pass:
                behavior_control_ok = (not gate["pass"] and gate["failed_stage"] == "test" and not detected)
                if not behavior_control_ok:
                    failures.append(
                        "behavior-only control did not show the intended complementarity "
                        f"(gate={gate['pass']}/{gate['failed_stage']}, morph={detected})"
                    )
            results.append(
                {
                    "name": name,
                    "kind": "control",
                    "morphostat_detected": detected,
                    "sensor_diffs": diffs,
                    "standard_rust_pass": gate["pass"],
                    "standard_failed_stage": gate["failed_stage"],
                    "extraction_seconds": round(seconds, 3),
                }
            )

        reset_repo(repo)
        morphology_bytes = len(json.dumps(baseline, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        source_bytes = scoped_source_bytes(repo)
        ratio = morphology_bytes / source_bytes if source_bytes else None
        median_seconds = statistics.median(extraction_times)
        max_seconds = max(extraction_times)

        if detected_positives != len(POSITIVES):
            failures.append(f"recall below 100%: {detected_positives}/{len(POSITIVES)}")
        if false_positives != 0:
            failures.append(f"false positives: {false_positives}")
        if median_seconds > 20.0:
            failures.append(f"median extraction time exceeded 20s: {median_seconds:.3f}s")
        if max_seconds > 60.0:
            failures.append(f"max extraction time exceeded 60s: {max_seconds:.3f}s")

        summary = {
            "upstream": {"repository": "BurntSushi/ripgrep", "commit": UPSTREAM_SHA},
            "scope": {
                "cargo_metadata": "full ripgrep workspace",
                "rustdoc_public_api": "ignore crate",
                "rust_analyzer_internal_edges": "ignore::overrides module cross-module dependencies",
            },
            "baseline_standard_gate": baseline_gate,
            "baseline_morphology_deterministic_3_of_3": deterministic,
            "metrics": {
                "structural_cases": len(POSITIVES),
                "structural_detected": detected_positives,
                "recall": round(detected_positives / len(POSITIVES), 4),
                "controls": len(CONTROLS),
                "false_positives": false_positives,
                "standard_rust_structural_detected": standard_detected,
                "additional_detections_while_standard_green": additional_while_standard_green,
                "behavior_control_complementarity": behavior_control_ok,
                "morphology_bytes": morphology_bytes,
                "scoped_source_bytes": source_bytes,
                "morphology_to_scoped_source_ratio": round(ratio, 4) if ratio is not None else None,
                "median_extraction_seconds": round(median_seconds, 3),
                "max_extraction_seconds": round(max_seconds, 3),
            },
            "baseline_internal_edges": baseline["ignore_overrides_semantic_edges"],
            "results": results,
            "failures": failures,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
