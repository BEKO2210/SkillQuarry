#!/usr/bin/env python3

import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

RUST = {
    "Cargo.toml": """[workspace]\nmembers = [\"domain\", \"storage\", \"service\", \"app\"]\nresolver = \"2\"\n""",
    "domain/Cargo.toml": """[package]\nname = \"domain\"\nversion = \"0.1.0\"\nedition = \"2024\"\n""",
    "domain/src/lib.rs": """pub mod audit;\npub mod policy;\npub mod value;\n\npub use policy::apply_policy;\npub use value::DomainValue;\n\npub const DOMAIN_REV: u32 = 1;\n""",
    "domain/src/value.rs": """#[derive(Clone, Copy, Debug, PartialEq, Eq)]\npub struct DomainValue(i32);\n\nimpl DomainValue {\n    pub fn new(value: i32) -> Self {\n        Self(value)\n    }\n\n    pub fn get(self) -> i32 {\n        self.0\n    }\n}\n""",
    "domain/src/policy.rs": """use crate::value::DomainValue;\n\npub(crate) const POLICY_MARKER: i32 = 11;\n\npub fn apply_policy(value: DomainValue) -> DomainValue {\n    DomainValue::new(value.get() + 1)\n}\n""",
    "domain/src/audit.rs": """use crate::value::DomainValue;\n\npub(crate) const AUDIT_MARKER: i32 = 7;\n\npub fn audit_code(value: DomainValue) -> i32 {\n    value.get() & 1\n}\n""",
    "storage/Cargo.toml": """[package]\nname = \"storage\"\nversion = \"0.1.0\"\nedition = \"2024\"\n\n[dependencies]\ndomain = { path = \"../domain\" }\n""",
    "storage/src/lib.rs": """use domain::DomainValue;\n\npub fn persist(value: DomainValue) -> DomainValue {\n    value\n}\n\npub fn load(seed: i32) -> DomainValue {\n    DomainValue::new(seed)\n}\n""",
    "service/Cargo.toml": """[package]\nname = \"service\"\nversion = \"0.1.0\"\nedition = \"2024\"\n\n[dependencies]\ndomain = { path = \"../domain\" }\nstorage = { path = \"../storage\" }\n""",
    "service/src/lib.rs": """use domain::{apply_policy, DomainValue};\nuse storage::persist;\n\nconst INTERNAL_SCALE: i32 = 2;\n\npub const SERVICE_REV: u32 = 1;\n\nfn normalize(value: i32) -> i32 {\n    value\n}\n\npub fn process(seed: i32) -> i32 {\n    let value = DomainValue::new(seed);\n    let adjusted = apply_policy(value);\n    let stored = persist(adjusted);\n    normalize(stored.get()) * INTERNAL_SCALE\n}\n""",
    "app/Cargo.toml": """[package]\nname = \"app\"\nversion = \"0.1.0\"\nedition = \"2024\"\n\n[features]\ndefault = [\"plain\"]\nplain = []\ndiagnostics = []\nlegacy = []\n\n[dependencies]\ndomain = { path = \"../domain\" }\nservice = { path = \"../service\" }\n""",
    "app/src/lib.rs": """pub mod ui;\n\npub fn run(seed: i32) -> String {\n    ui::render(service::process(seed))\n}\n""",
    "app/src/ui.rs": """pub fn render(value: i32) -> String {\n    format!(\"value={value}\")\n}\n""",
    "app/tests/integration.rs": """#[test]\nfn application_behavior_is_stable() {\n    assert_eq!(app::run(5), \"value=12\");\n}\n\n#[test]\nfn domain_audit_is_stable() {\n    let value = domain::DomainValue::new(5);\n    assert_eq!(domain::audit::audit_code(value), 1);\n}\n""",
}

PUBLIC_ITEM = re.compile(
    r"^\s*pub(?:\([^)]*\))?\s+(?:(?:async|unsafe)\s+)*(?:fn|struct|enum|trait|const|type)\b"
)
PUBLIC_USE = re.compile(r"^\s*pub\s+use\s+")
PUBLIC_MOD = re.compile(r"^\s*pub\s+mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;")
CRATE_USE = re.compile(r"^\s*use\s+crate::([A-Za-z_][A-Za-z0-9_]*)")
GROUP_CRATE_USE = re.compile(r"^\s*use\s+crate::\{([^}]*)\}\s*;")


def write_workspace(root: Path) -> None:
    for rel, content in RUST.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def replace(path: Path, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise AssertionError(f"mutation anchor missing in {path}: {old!r}")
    write(path, text.replace(old, new, 1))


def normalize_public_line(line: str) -> str:
    line = " ".join(line.strip().split())
    if "{" in line:
        line = line.split("{", 1)[0].rstrip()
    return line


def crate_name(crate_dir: Path) -> str:
    data = tomllib.loads(read(crate_dir / "Cargo.toml"))
    return data["package"]["name"]


def source_module(path: Path, src: Path) -> str:
    rel = path.relative_to(src)
    if rel.name == "lib.rs":
        return "__root__"
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "mod":
        parts = parts[:-1]
    return "::".join(parts)


def parse_internal_edges(src: Path) -> list[str]:
    edges: set[str] = set()
    for path in sorted(src.rglob("*.rs")):
        origin = source_module(path, src)
        for line in read(path).splitlines():
            match = CRATE_USE.match(line)
            if match:
                target = match.group(1)
                if origin != "__root__" and target != origin.split("::", 1)[0]:
                    edges.add(f"{origin}->{target}")
                continue
            grouped = GROUP_CRATE_USE.match(line)
            if grouped and origin != "__root__":
                for raw in grouped.group(1).split(","):
                    target = raw.strip().split("::", 1)[0].split(" as ", 1)[0].strip()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target):
                        edges.add(f"{origin}->{target}")
    return sorted(edges)


def extract_crate(crate_dir: Path) -> dict:
    cargo = tomllib.loads(read(crate_dir / "Cargo.toml"))
    src = crate_dir / "src"
    deps = sorted((cargo.get("dependencies") or {}).keys())
    features = {
        name: sorted(values)
        for name, values in sorted((cargo.get("features") or {}).items())
    }
    public_api: list[str] = []
    public_modules: set[str] = set()
    for path in sorted(src.rglob("*.rs")):
        module = source_module(path, src)
        for line in read(path).splitlines():
            if module == "__root__":
                match = PUBLIC_MOD.match(line)
                if match:
                    public_modules.add(match.group(1))
            if PUBLIC_ITEM.match(line) or PUBLIC_USE.match(line):
                public_api.append(f"{module}:{normalize_public_line(line)}")
    return {
        "dependencies": deps,
        "features": features,
        "public_api": sorted(public_api),
        "public_modules": sorted(public_modules),
        "internal_edges": parse_internal_edges(src),
    }


def extract_morphology(root: Path) -> dict:
    workspace = tomllib.loads(read(root / "Cargo.toml"))["workspace"]
    members = workspace["members"]
    crates: dict[str, dict] = {}
    for member in members:
        crate_dir = root / member
        name = crate_name(crate_dir)
        crates[name] = extract_crate(crate_dir)
    return {"schema": 1, "crates": dict(sorted(crates.items()))}


def compare_morphology(target: dict, actual: dict) -> list[dict]:
    violations: list[dict] = []
    target_names = set(target["crates"])
    actual_names = set(actual["crates"])
    for name in sorted(target_names - actual_names):
        violations.append({"kind": "missing_crate", "subject": name})
    for name in sorted(actual_names - target_names):
        violations.append({"kind": "extra_crate", "subject": name})
    for name in sorted(target_names & actual_names):
        expected = target["crates"][name]
        observed = actual["crates"][name]
        for field, kind in (
            ("dependencies", "dependency_drift"),
            ("features", "feature_drift"),
            ("public_api", "public_api_drift"),
            ("public_modules", "public_module_drift"),
            ("internal_edges", "internal_edge_drift"),
        ):
            if expected[field] != observed[field]:
                violations.append({"kind": kind, "subject": name})
    return violations


def run(root: Path, args: list[str], target_dir: Path) -> tuple[bool, str]:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    completed = subprocess.run(
        args,
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120,
        check=False,
    )
    return completed.returncode == 0, completed.stdout[-3000:]


def standard_rust_gate(root: Path, target_dir: Path) -> tuple[bool, dict]:
    checks = {}
    for name, args in (
        ("check", ["cargo", "check", "--workspace", "--all-targets"]),
        ("clippy", ["cargo", "clippy", "--workspace", "--all-targets", "--", "-D", "warnings"]),
        ("test", ["cargo", "test", "--workspace", "--quiet"]),
    ):
        ok, output = run(root, args, target_dir)
        checks[name] = {"pass": ok, "tail": output}
        if not ok:
            return False, checks
    return True, checks


def m_app_direct_storage(root: Path) -> None:
    path = root / "app/Cargo.toml"
    write(path, read(path) + "storage = { path = \"../storage\" }\n")


def m_policy_to_audit(root: Path) -> None:
    path = root / "domain/src/policy.rs"
    replace(path, "use crate::value::DomainValue;", "use crate::audit;\nuse crate::value::DomainValue;")
    replace(path, "pub fn apply_policy(value: DomainValue) -> DomainValue {", "pub fn apply_policy(value: DomainValue) -> DomainValue {\n    let _ = audit::AUDIT_MARKER;")


def m_internal_cycle(root: Path) -> None:
    m_policy_to_audit(root)
    path = root / "domain/src/audit.rs"
    replace(path, "use crate::value::DomainValue;", "use crate::policy;\nuse crate::value::DomainValue;")
    replace(path, "pub fn audit_code(value: DomainValue) -> i32 {", "pub fn audit_code(value: DomainValue) -> i32 {\n    let _ = policy::POLICY_MARKER;")


def m_signature_drift(root: Path) -> None:
    replace(root / "app/src/ui.rs", "pub fn render(value: i32) -> String", "pub fn render(value: i64) -> String")
    replace(root / "app/src/lib.rs", "ui::render(service::process(seed))", "ui::render(i64::from(service::process(seed)))")


def m_visibility_widen(root: Path) -> None:
    replace(root / "service/src/lib.rs", "fn normalize(value: i32) -> i32", "pub fn normalize(value: i32) -> i32")


def m_public_removed(root: Path) -> None:
    replace(root / "service/src/lib.rs", "pub const SERVICE_REV: u32 = 1;\n\n", "")


def m_public_added(root: Path) -> None:
    path = root / "service/src/lib.rs"
    write(path, read(path) + "\npub fn diagnostic_probe() -> bool {\n    true\n}\n")


def m_default_feature(root: Path) -> None:
    replace(root / "app/Cargo.toml", 'default = ["plain"]', 'default = ["plain", "diagnostics"]')


def m_remove_feature(root: Path) -> None:
    replace(root / "app/Cargo.toml", "legacy = []\n", "")


def m_rename_storage(root: Path) -> None:
    shutil.move(root / "storage", root / "persistence")
    replace(root / "persistence/Cargo.toml", 'name = "storage"', 'name = "persistence"')
    replace(root / "Cargo.toml", '"storage"', '"persistence"')
    replace(root / "service/Cargo.toml", 'storage = { path = "../storage" }', 'persistence = { path = "../persistence" }')
    replace(root / "service/src/lib.rs", "use storage::persist;", "use persistence::persist;")


def m_absorb_storage(root: Path) -> None:
    shutil.rmtree(root / "storage")
    replace(root / "Cargo.toml", ', "storage"', "")
    replace(root / "service/Cargo.toml", 'storage = { path = "../storage" }\n', "")
    replace(root / "service/src/lib.rs", "use storage::persist;", "fn persist(value: DomainValue) -> DomainValue {\n    value\n}")


def m_add_workspace_crate(root: Path) -> None:
    replace(root / "Cargo.toml", '"app"]', '"app", "observer"]')
    write(root / "observer/Cargo.toml", '[package]\nname = "observer"\nversion = "0.1.0"\nedition = "2024"\n')
    write(root / "observer/src/lib.rs", "pub fn observe() -> bool {\n    true\n}\n")


def m_rename_public_module(root: Path) -> None:
    shutil.move(root / "domain/src/audit.rs", root / "domain/src/telemetry.rs")
    replace(root / "domain/src/lib.rs", "pub mod audit;", "pub mod telemetry;")
    replace(root / "app/tests/integration.rs", "domain::audit::audit_code", "domain::telemetry::audit_code")


def m_add_public_module(root: Path) -> None:
    path = root / "domain/src/lib.rs"
    replace(path, "pub mod value;", "pub mod value;\npub mod extra;")
    write(root / "domain/src/extra.rs", "pub fn noop() -> bool {\n    true\n}\n")


def m_broken_dependency(root: Path) -> None:
    replace(root / "service/Cargo.toml", 'storage = { path = "../storage" }\n', "")


def c_behavior_bug(root: Path) -> None:
    replace(root / "service/src/lib.rs", "const INTERNAL_SCALE: i32 = 2;", "const INTERNAL_SCALE: i32 = 3;")


def c_private_helper(root: Path) -> None:
    path = root / "service/src/lib.rs"
    replace(path, "fn normalize(value: i32) -> i32 {\n    value\n}", "fn normalize(value: i32) -> i32 {\n    value + private_zero()\n}\n\nfn private_zero() -> i32 {\n    0\n}")


def c_comment_only(root: Path) -> None:
    path = root / "domain/src/value.rs"
    write(path, "// Internal implementation note: representation stays private.\n" + read(path))


def c_algorithm_refactor(root: Path) -> None:
    path = root / "service/src/lib.rs"
    replace(path, "fn normalize(value: i32) -> i32 {\n    value\n}\n\n", "")
    replace(path, "normalize(stored.get()) * INTERNAL_SCALE", "stored.get() * INTERNAL_SCALE")


def c_extra_test(root: Path) -> None:
    write(root / "app/tests/extra.rs", "#[test]\nfn zero_case_is_stable() {\n    assert_eq!(app::run(0), \"value=2\");\n}\n")


def c_import_reorder(root: Path) -> None:
    path = root / "service/src/lib.rs"
    replace(path, "use domain::{apply_policy, DomainValue};\nuse storage::persist;", "use storage::persist;\nuse domain::{apply_policy, DomainValue};")


SCENARIOS = [
    ("healthy_baseline", "control", None, None),
    ("app_direct_storage_dependency", "structural", m_app_direct_storage, "dependency_drift"),
    ("domain_policy_to_audit_edge", "structural", m_policy_to_audit, "internal_edge_drift"),
    ("domain_internal_cycle", "structural", m_internal_cycle, "internal_edge_drift"),
    ("public_signature_drift", "structural", m_signature_drift, "public_api_drift"),
    ("private_to_public_visibility", "structural", m_visibility_widen, "public_api_drift"),
    ("public_item_removed", "structural", m_public_removed, "public_api_drift"),
    ("public_item_added", "structural", m_public_added, "public_api_drift"),
    ("default_feature_drift", "structural", m_default_feature, "feature_drift"),
    ("feature_removed", "structural", m_remove_feature, "feature_drift"),
    ("crate_renamed_storage_to_persistence", "structural", m_rename_storage, "missing_crate"),
    ("storage_crate_absorbed", "structural", m_absorb_storage, "missing_crate"),
    ("new_workspace_crate", "structural", m_add_workspace_crate, "extra_crate"),
    ("public_module_renamed", "structural", m_rename_public_module, "public_module_drift"),
    ("new_public_module", "structural", m_add_public_module, "public_module_drift"),
    ("broken_declared_dependency", "structural", m_broken_dependency, "dependency_drift"),
    ("behavior_only_bug", "control", c_behavior_bug, None),
    ("private_helper_refactor", "control", c_private_helper, None),
    ("comment_only", "control", c_comment_only, None),
    ("algorithm_refactor_same_behavior", "control", c_algorithm_refactor, None),
    ("test_only_strengthening", "control", c_extra_test, None),
    ("import_reordering", "control", c_import_reorder, None),
]


def source_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file() and (path.name == "Cargo.toml" or "src" in path.parts):
            total += path.stat().st_size
    return total


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="morphostat-pro-") as tmp:
        arena = Path(tmp)
        healthy = arena / "healthy"
        healthy.mkdir()
        write_workspace(healthy)
        target = extract_morphology(healthy)
        target_json = json.dumps(target, sort_keys=True, separators=(",", ":")).encode()
        source_size = source_bytes(healthy)
        shared_target = arena / "cargo-target"

        results = []
        failures = []
        for index, (name, category, mutation, expected_kind) in enumerate(SCENARIOS):
            case = arena / f"case-{index:02d}-{name}"
            shutil.copytree(healthy, case)
            if mutation is not None:
                mutation(case)
            actual = extract_morphology(case)
            violations = compare_morphology(target, actual)
            kinds = sorted({item["kind"] for item in violations})
            morph_detected = bool(violations)
            standard_pass, checks = standard_rust_gate(case, shared_target)

            if category == "structural":
                if not morph_detected:
                    failures.append(f"{name}: structural mutation escaped morphology")
                if expected_kind not in kinds:
                    failures.append(f"{name}: expected {expected_kind}, got {kinds}")
            else:
                if morph_detected:
                    failures.append(f"{name}: false positive {kinds}")

            if name == "healthy_baseline" and not standard_pass:
                failures.append("healthy_baseline: standard Rust gate failed")
            if name == "behavior_only_bug" and standard_pass:
                failures.append("behavior_only_bug: standard Rust gate should fail")

            results.append(
                {
                    "name": name,
                    "category": category,
                    "standard_pass": standard_pass,
                    "morph_detected": morph_detected,
                    "violation_kinds": kinds,
                    "failed_standard_stage": next(
                        (stage for stage, result in checks.items() if not result["pass"]),
                        None,
                    ),
                }
            )

        positives = [r for r in results if r["category"] == "structural"]
        negatives = [r for r in results if r["category"] == "control"]
        true_positive = sum(r["morph_detected"] for r in positives)
        false_positive = sum(r["morph_detected"] for r in negatives)
        standard_structural_detected = sum(not r["standard_pass"] for r in positives)
        additional = sum(r["standard_pass"] and r["morph_detected"] for r in positives)

        if true_positive != len(positives):
            failures.append(f"recall: {true_positive}/{len(positives)}")
        if false_positive != 0:
            failures.append(f"false positives: {false_positive}/{len(negatives)}")
        if additional < 12:
            failures.append(f"additional latent detections too low: {additional}")

        summary = {
            "failures": failures,
            "metrics": {
                "scenarios": len(results),
                "structural_cases": len(positives),
                "control_cases": len(negatives),
                "morphostat_structural_detected": true_positive,
                "standard_rust_structural_detected": standard_structural_detected,
                "additional_structural_detections_while_standard_green": additional,
                "false_positives": false_positive,
                "target_morphology_bytes": len(target_json),
                "healthy_source_bytes": source_size,
                "morphology_to_source_ratio": round(len(target_json) / source_size, 4),
            },
            "results": results,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
