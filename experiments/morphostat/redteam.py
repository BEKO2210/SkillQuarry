#!/usr/bin/env python3

import json
import shutil
import tempfile
from pathlib import Path

import pro_test as p

p.RUST["domain/src/policy.rs"] = """use crate::value::DomainValue;

pub(crate) const POLICY_MARKER: i32 = 11;

pub fn apply_policy(value: DomainValue) -> DomainValue {
    let _ = POLICY_MARKER;
    DomainValue::new(value.get() + 1)
}
"""

p.RUST["domain/src/audit.rs"] = """use crate::value::DomainValue;

pub(crate) const AUDIT_MARKER: i32 = 7;

pub fn audit_code(value: DomainValue) -> i32 {
    let _ = AUDIT_MARKER;
    value.get() & 1
}
"""


def base(root: Path) -> None:
    root.mkdir(parents=True)
    p.write_workspace(root)


def direct_qualified_reference(root: Path) -> None:
    path = root / "domain/src/policy.rs"
    p.replace(
        path,
        "pub fn apply_policy(value: DomainValue) -> DomainValue {",
        "pub fn apply_policy(value: DomainValue) -> DomainValue {\n    let _ = crate::audit::AUDIT_MARKER;",
    )


def crate_alias_reference(root: Path) -> None:
    path = root / "domain/src/policy.rs"
    p.replace(path, "use crate::value::DomainValue;", "use crate as root;\nuse crate::value::DomainValue;")
    p.replace(
        path,
        "pub fn apply_policy(value: DomainValue) -> DomainValue {",
        "pub fn apply_policy(value: DomainValue) -> DomainValue {\n    let _ = root::audit::AUDIT_MARKER;",
    )


def target_specific_dependency(root: Path) -> None:
    path = root / "app/Cargo.toml"
    p.write(path, p.read(path) + "\n[target.'cfg(unix)'.dependencies]\nstorage = { path = \"../storage\" }\n")


def setup_trait(root: Path) -> None:
    path = root / "domain/src/lib.rs"
    p.write(path, p.read(path) + "\npub trait Transform {\n    fn transform(&self, value: i32) -> i32;\n}\n")


def mutate_trait(root: Path) -> None:
    p.replace(root / "domain/src/lib.rs", "fn transform(&self, value: i32) -> i32;", "fn transform(&self, value: i64) -> i64;")


def setup_public_struct(root: Path) -> None:
    path = root / "domain/src/lib.rs"
    p.write(path, p.read(path) + "\npub struct Config {\n    pub threshold: i32,\n}\n")


def mutate_public_struct(root: Path) -> None:
    p.replace(root / "domain/src/lib.rs", "pub threshold: i32,", "pub threshold: i64,")


def setup_macro_api(root: Path) -> None:
    path = root / "app/src/lib.rs"
    p.write(
        path,
        p.read(path)
        + """
macro_rules! export_probe {
    ($ty:ty) => {
        pub fn generated_probe(value: $ty) -> $ty {
            value
        }
    };
}

export_probe!(i32);
""",
    )


def mutate_macro_api(root: Path) -> None:
    p.replace(root / "app/src/lib.rs", "export_probe!(i32);", "export_probe!(i64);")


def setup_multiline_signature(root: Path) -> None:
    p.write(
        root / "app/src/ui.rs",
        """pub fn render(
    value: i32,
) -> String {
    format!("value={value}")
}
""",
    )


def mutate_multiline_signature(root: Path) -> None:
    p.replace(root / "app/src/ui.rs", "value: i32,", "value: i64,")
    p.replace(
        root / "app/src/lib.rs",
        "ui::render(service::process(seed))",
        "ui::render(i64::from(service::process(seed)))",
    )


CASES = [
    ("direct_qualified_internal_reference", None, direct_qualified_reference),
    ("crate_alias_internal_reference", None, crate_alias_reference),
    ("target_specific_dependency", None, target_specific_dependency),
    ("trait_method_signature_drift", setup_trait, mutate_trait),
    ("public_struct_field_type_drift", setup_public_struct, mutate_public_struct),
    ("macro_generated_public_api_drift", setup_macro_api, mutate_macro_api),
    ("multiline_public_signature_drift", setup_multiline_signature, mutate_multiline_signature),
]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="morphostat-redteam-") as tmp:
        arena = Path(tmp)
        target_dir = arena / "cargo-target"
        results = []
        infrastructure_failures = []
        for index, (name, setup, mutate) in enumerate(CASES):
            healthy = arena / f"healthy-{index}"
            base(healthy)
            if setup:
                setup(healthy)
            standard_healthy, _ = p.standard_rust_gate(healthy, target_dir)
            if not standard_healthy:
                infrastructure_failures.append(f"{name}: custom healthy baseline failed Rust gate")
                continue
            target = p.extract_morphology(healthy)
            actual_root = arena / f"actual-{index}"
            shutil.copytree(healthy, actual_root)
            mutate(actual_root)
            standard_pass, _ = p.standard_rust_gate(actual_root, target_dir)
            violations = p.compare_morphology(target, p.extract_morphology(actual_root))
            results.append(
                {
                    "name": name,
                    "standard_rust_pass": standard_pass,
                    "morphostat_detected": bool(violations),
                    "violation_kinds": sorted({item["kind"] for item in violations}),
                }
            )

        silent_misses = sum(
            result["standard_rust_pass"] and not result["morphostat_detected"]
            for result in results
        )
        summary = {
            "infrastructure_failures": infrastructure_failures,
            "adversarial_cases": len(results),
            "silent_misses": silent_misses,
            "results": results,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 1 if infrastructure_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
