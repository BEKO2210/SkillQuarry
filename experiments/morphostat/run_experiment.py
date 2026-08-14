#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixture"
SPEC = HERE / "morphology.json"
DETECTOR = HERE / "morphostat.py"


def run(command: list[str], cwd: Path, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def cargo_passes(root: Path) -> tuple[bool, str]:
    result = run(["cargo", "test", "--quiet", "--all-targets"], root)
    return result.returncode == 0, result.stdout


def morphology_passes(root: Path) -> tuple[bool, dict]:
    result = run(
        [sys.executable, str(DETECTOR), "--root", str(root), "--spec", str(SPEC)],
        HERE,
    )
    payload = json.loads(result.stdout)
    return result.returncode == 0, payload


def mutate_forbidden_dependency(root: Path) -> None:
    (root / "src" / "domain.rs").write_text(
        "use crate::ui;\n\n"
        "pub fn apply_delta(value: i32, delta: i32) -> i32 {\n"
        "    let _presentation_leak = ui::label(value);\n"
        "    value + delta\n"
        "}\n",
        encoding="utf-8",
    )


def mutate_absorbed_module(root: Path) -> None:
    (root / "src" / "storage.rs").unlink()
    lib = (root / "src" / "lib.rs").read_text(encoding="utf-8")
    (root / "src" / "lib.rs").write_text(
        lib.replace("pub mod storage;\n", ""), encoding="utf-8"
    )
    (root / "src" / "service.rs").write_text(
        "use crate::domain;\n\n"
        "pub fn process(value: i32) -> i32 {\n"
        "    let adjusted = domain::apply_delta(value, 1);\n"
        "    let persisted = domain::apply_delta(adjusted, 0);\n"
        "    persisted * 2\n"
        "}\n",
        encoding="utf-8",
    )


def mutate_public_api(root: Path) -> None:
    (root / "src" / "ui.rs").write_text(
        "use crate::service;\n\n"
        "pub fn render(value: i64) -> String {\n"
        "    format!(\"value={}\", service::process(value as i32))\n"
        "}\n\n"
        "pub fn label(value: i32) -> String {\n"
        "    format!(\"label:{value}\")\n"
        "}\n",
        encoding="utf-8",
    )


def mutate_behavior_only(root: Path) -> None:
    service = (root / "src" / "service.rs").read_text(encoding="utf-8")
    (root / "src" / "service.rs").write_text(
        service.replace("storage::persist(adjusted) * 2", "storage::persist(adjusted) * 3"),
        encoding="utf-8",
    )


def execute_scenario(name: str, mutator) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"morphostat-{name}-") as temp:
        root = Path(temp) / "fixture"
        shutil.copytree(FIXTURE, root)
        if mutator is not None:
            mutator(root)

        cargo_ok, cargo_output = cargo_passes(root)
        morph_ok, morph_payload = morphology_passes(root)
        return {
            "name": name,
            "cargo_tests_pass": cargo_ok,
            "morphology_pass": morph_ok,
            "violations": morph_payload.get("violations", []),
            "cargo_tail": cargo_output[-1200:],
        }


def main() -> int:
    scenarios = [
        execute_scenario("healthy_baseline", None),
        execute_scenario("latent_forbidden_dependency", mutate_forbidden_dependency),
        execute_scenario("latent_required_module_absorbed", mutate_absorbed_module),
        execute_scenario("latent_public_api_drift", mutate_public_api),
        execute_scenario("behavior_only_bug", mutate_behavior_only),
    ]

    expected = {
        "healthy_baseline": (True, True),
        "latent_forbidden_dependency": (True, False),
        "latent_required_module_absorbed": (True, False),
        "latent_public_api_drift": (True, False),
        "behavior_only_bug": (False, True),
    }

    failures: list[str] = []
    for scenario in scenarios:
        actual = (scenario["cargo_tests_pass"], scenario["morphology_pass"])
        wanted = expected[scenario["name"]]
        if actual != wanted:
            failures.append(f"{scenario['name']}: expected {wanted}, got {actual}")

    print(json.dumps({"scenarios": scenarios, "failures": failures}, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
