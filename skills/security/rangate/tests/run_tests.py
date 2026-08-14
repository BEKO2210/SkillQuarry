#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[2]
FIXTURE = SKILL_ROOT / "tests" / "fixture"

# CI sets this so a missing toolchain fails the run instead of quietly skipping.
REQUIRE_TOOLCHAIN = os.environ.get("RANGATE_REQUIRE_TOOLCHAIN") == "1"
COMPILE_FAIL_PATTERN = re.compile(r"^/// ```compile_fail(?:,(?P<code>E\d{4}))?\s*$")


def require(case: unittest.TestCase, *tools: str) -> None:
    """Skip where a tool is genuinely absent; fail where CI promised it would exist."""
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if not missing:
        return
    message = f"missing on this machine: {', '.join(missing)}"
    if REQUIRE_TOOLCHAIN:
        case.fail(f"RANGATE_REQUIRE_TOOLCHAIN=1 but {message}")
    case.skipTest(message + " — install it to run this check locally")


def compile_fail_snippets() -> list[tuple[int, str | None, str]]:
    """Every compile_fail doctest in the fixture: line number, pinned code, source."""
    found: list[tuple[int, str | None, str]] = []
    lines = (FIXTURE / "src" / "lib.rs").read_text("utf-8").splitlines()
    index = 0
    while index < len(lines):
        match = COMPILE_FAIL_PATTERN.match(lines[index])
        if not match:
            index += 1
            continue
        start = index + 1
        body: list[str] = []
        index = start
        while index < len(lines) and lines[index].strip() != "/// ```":
            body.append(lines[index].removeprefix("/// ").removeprefix("///"))
            index += 1
        found.append((start, match.group("code"), "\n".join(body)))
        index += 1
    return found


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
        self.assertEqual(manifest["tests"]["count"], 14)

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
        require(self, *("cargo",))
        result = run_command(["cargo", "fmt", "--check"], cwd=FIXTURE)
        assert_success(self, result)

    def test_07_cargo_check(self) -> None:
        require(self, *("cargo",))
        result = run_command(["cargo", "check", "--all-targets"], cwd=FIXTURE)
        assert_success(self, result)

    def test_08_strict_unsafe_operation_lint(self) -> None:
        require(self, *("cargo",))
        result = run_command(
            ["cargo", "check", "--all-targets"],
            cwd=FIXTURE,
            env={"RUSTFLAGS": "-Dunsafe_op_in_unsafe_fn"},
        )
        assert_success(self, result)

    def test_09_clippy_denies_warnings(self) -> None:
        require(self, *("cargo",))
        result = run_command(
            ["cargo", "clippy", "--all-targets", "--", "-D", "warnings"],
            cwd=FIXTURE,
        )
        assert_success(self, result)

    def test_10_runtime_scenarios(self) -> None:
        require(self, *("cargo", "cc"))
        result = run_command(
            ["cargo", "test", "--all-targets", "--", "--nocapture"],
            cwd=FIXTURE,
        )
        assert_success(self, result)
        self.assertIn("5 passed; 0 failed", result.stdout)

    def test_11_compile_fail_proofs(self) -> None:
        require(self, *("cargo",))
        result = run_command(["cargo", "test", "--doc"], cwd=FIXTURE)
        assert_success(self, result)
        self.assertIn("3 passed; 0 failed", result.stdout)

    def test_12_release_mode_scenarios(self) -> None:
        require(self, *("cargo", "cc"))
        result = run_command(
            ["cargo", "test", "--release", "--all-targets"],
            cwd=FIXTURE,
        )
        assert_success(self, result)
        self.assertIn("5 passed; 0 failed", result.stdout)

    def test_13_rustdoc_builds_without_dependencies(self) -> None:
        require(self, *("cargo",))
        result = run_command(["cargo", "doc", "--no-deps"], cwd=FIXTURE)
        assert_success(self, result)


    def test_14_compile_fail_reasons_are_verified_not_assumed(self) -> None:
        """rustdoc accepts any compilation error, so prove the *reason* with rustc.

        On stable, `compile_fail,E0382` is not enforced: a snippet with a typo, or
        one annotated with an error code that does not exist, still counts as a
        pass. Each snippet is therefore compiled directly and its emitted error
        codes are checked.
        """
        snippets = compile_fail_snippets()
        self.assertEqual(len(snippets), 3, msg="expected three compile-fail proofs")
        for line, code, _body in snippets:
            self.assertIsNotNone(code, msg=f"compile_fail block at line {line} pins no error code")

        require(self, "cargo", "rustc")
        assert_success(self, run_command(["cargo", "build"], cwd=FIXTURE))
        rlib = FIXTURE / "target" / "debug" / "librangate_fixture.rlib"
        self.assertTrue(rlib.is_file(), msg="fixture rlib was not produced")

        def emitted_codes(source: str) -> tuple[int, set[str]]:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "snippet.rs"
                path.write_text(f"fn main() {{\n{source}\n}}\n", encoding="utf-8")
                result = run_command([
                    "rustc", "--edition", "2024", "--crate-type", "bin",
                    "--error-format=json",
                    "--extern", f"rangate_fixture={rlib}",
                    "-L", f"dependency={FIXTURE / 'target' / 'debug' / 'deps'}",
                    "-o", os.devnull, str(path),
                ], cwd=FIXTURE)
            codes = set()
            for line in result.stdout.splitlines():
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                code = (payload.get("code") or {}).get("code")
                if code:
                    codes.add(code)
            return result.returncode, codes

        for line, code, body in snippets:
            status, codes = emitted_codes(body)
            self.assertNotEqual(status, 0, msg=f"snippet at line {line} compiled successfully")
            self.assertIn(code, codes, msg=f"snippet at line {line} failed with {sorted(codes)}, not {code}")

        # Control: a snippet that fails for an unrelated reason must not satisfy the
        # pinned code. Without this, the check above could pass vacuously.
        broken = snippets[0][2].replace("Device::", "DeviceTypo::", 1)
        status, codes = emitted_codes(broken)
        self.assertNotEqual(status, 0)
        self.assertNotIn(snippets[0][1], codes)


if __name__ == "__main__":
    if shutil.which("python3") is None:
        raise SystemExit("python3 is required")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RanGateTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
