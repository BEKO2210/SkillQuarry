#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[2]
FIXTURE = SKILL_ROOT / "tests" / "fixture"


def run_command(
    args: list[str],
    *,
    cwd: Path = SKILL_ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            env=merged,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AssertionError(f"required executable not found: {args[0]}") from exc


def assert_success(case: unittest.TestCase, result: subprocess.CompletedProcess[str]) -> None:
    case.assertEqual(result.returncode, 0, msg=result.stdout)


class RanGateTests(unittest.TestCase):
    def test_01_manifest_contract(self) -> None:
        manifest = json.loads((SKILL_ROOT / "skill.json").read_text("utf-8"))
        self.assertEqual(manifest["name"], "rangate")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["category"], "security")
        self.assertEqual(manifest["license"], "Apache-2.0")
        self.assertEqual(manifest["requires"]["packages"], [])
        self.assertEqual(manifest["workflow"], "rangate-tests.yml")
        self.assertEqual(manifest["tests"]["count"], 13)

    def test_02_skill_contract_and_size(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text("utf-8")
        lines = skill.splitlines()
        self.assertLessEqual(len(lines), 500)
        self.assertTrue(skill.startswith("---\nname: rangate\n"))
        self.assertIn("description:", skill)
        for phase in (
            "# Phase 1 — Map the membrane",
            "# Phase 2 — Build the pore",
            "# Phase 3 — Establish directionality with compiler feedback",
            "# Phase 4 — Attack the membrane",
        ):
            self.assertIn(phase, skill)
        for section in (
            "## RANGATE_RESULT",
            "## MEMBRANE",
            "## PROOF_OBLIGATIONS",
            "## COMPILER_EVIDENCE",
            "## REFACTORED_CODE",
            "## REMAINING_RISK",
        ):
            self.assertIn(section, skill)
        self.assertIn("Do not install a new Rust toolchain", skill)
        self.assertIn("unsafe impl Send", skill)
        self.assertIn("UNVERIFIED", skill)

    def test_03_reference_assets_and_docs_exist(self) -> None:
        required = (
            SKILL_ROOT / "REFERENCE.md",
            SKILL_ROOT / "README.md",
            SKILL_ROOT / "TEST_REPORT.md",
            SKILL_ROOT / "REVIEW.md",
            REPO_ROOT / "assets" / "rangate-logo.svg",
            REPO_ROOT / "assets" / "rangate-banner.svg",
        )
        for path in required:
            self.assertTrue(path.is_file(), msg=str(path))
        for svg in required[-2:]:
            text = svg.read_text("utf-8")
            self.assertIn("<svg", text)
            self.assertNotIn("<image", text.lower())
            self.assertNotIn("data:image", text.lower())

    def test_04_installer_round_trip_is_idempotent_and_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rangate skills ") as tmp:
            skills_root = Path(tmp) / "custom skills"
            env = {"RANGATE_SKILLS_DIR": str(skills_root)}
            first = run_command(["bash", "install.sh"], env=env)
            assert_success(self, first)
            second = run_command(["bash", "install.sh"], env=env)
            assert_success(self, second)

            target = skills_root / "rangate"
            self.assertEqual(
                (target / "SKILL.md").read_bytes(),
                (SKILL_ROOT / "SKILL.md").read_bytes(),
            )
            self.assertEqual(
                (target / "REFERENCE.md").read_bytes(),
                (SKILL_ROOT / "REFERENCE.md").read_bytes(),
            )

            extra = target / "user-note.txt"
            extra.write_text("keep me\n", encoding="utf-8")
            removed = run_command(["bash", "uninstall.sh"], env=env)
            assert_success(self, removed)
            self.assertFalse((target / "SKILL.md").exists())
            self.assertFalse((target / "REFERENCE.md").exists())
            self.assertEqual(extra.read_text("utf-8"), "keep me\n")

    def test_05_fixture_has_no_third_party_dependencies(self) -> None:
        cargo = (FIXTURE / "Cargo.toml").read_text("utf-8")
        self.assertIn('name = "rangate-fixture"', cargo)
        self.assertIn('edition = "2024"', cargo)
        self.assertNotIn("[dependencies]", cargo)
        self.assertNotIn("[dev-dependencies]", cargo)
        self.assertIn('unsafe_op_in_unsafe_fn = "deny"', cargo)

    def test_06_rustfmt(self) -> None:
        result = run_command(["cargo", "fmt", "--check"], cwd=FIXTURE)
        assert_success(self, result)

    def test_07_cargo_check(self) -> None:
        result = run_command(["cargo", "check", "--all-targets"], cwd=FIXTURE)
        assert_success(self, result)

    def test_08_strict_unsafe_operation_lint(self) -> None:
        result = run_command(
            ["cargo", "check", "--all-targets"],
            cwd=FIXTURE,
            env={"RUSTFLAGS": "-Dunsafe_op_in_unsafe_fn"},
        )
        assert_success(self, result)

    def test_09_clippy_denies_warnings(self) -> None:
        result = run_command(
            ["cargo", "clippy", "--all-targets", "--", "-D", "warnings"],
            cwd=FIXTURE,
        )
        assert_success(self, result)

    def test_10_runtime_scenarios(self) -> None:
        result = run_command(
            ["cargo", "test", "--all-targets", "--", "--nocapture"],
            cwd=FIXTURE,
        )
        assert_success(self, result)
        self.assertIn("5 passed; 0 failed", result.stdout)

    def test_11_compile_fail_proofs(self) -> None:
        result = run_command(["cargo", "test", "--doc"], cwd=FIXTURE)
        assert_success(self, result)
        self.assertIn("3 passed; 0 failed", result.stdout)

    def test_12_release_mode_scenarios(self) -> None:
        result = run_command(
            ["cargo", "test", "--release", "--all-targets"],
            cwd=FIXTURE,
        )
        assert_success(self, result)
        self.assertIn("5 passed; 0 failed", result.stdout)

    def test_13_rustdoc_builds_without_dependencies(self) -> None:
        result = run_command(["cargo", "doc", "--no-deps"], cwd=FIXTURE)
        assert_success(self, result)


if __name__ == "__main__":
    if shutil.which("python3") is None:
        raise SystemExit("python3 is required")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RanGateTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
