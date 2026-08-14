#!/usr/bin/env python3
"""Tests for the scaffolder, including that what it produces actually runs.

    python3 tools/test_new_skill.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import new_skill as ns
import validate_skills as vs


class TemplateIntegrityTests(unittest.TestCase):
    """The template is the example; if it rots, every future skill inherits the rot."""

    def test_template_manifest_validates_against_the_schema(self):
        schema = json.loads(vs.SCHEMA_PATH.read_text("utf-8"))
        manifest = json.loads((ns.TEMPLATE / "skill.json").read_text("utf-8"))
        self.assertEqual(vs.validate(manifest, schema, "template"), [])

    def test_template_has_every_required_file(self):
        for required in ("skill.json", "SKILL.md", "README.md", "TEST_REPORT.md",
                         "install.sh", "uninstall.sh", "tests/run_tests.py"):
            self.assertTrue((ns.TEMPLATE / required).is_file(), required)

    def test_template_is_not_in_the_marketplace(self):
        self.assertFalse((vs.SKILLS_DIR / "utilities" / "example-skill").exists())

    def test_template_suite_passes_its_own_gate(self):
        result = subprocess.run(
            [sys.executable, "tests/run_tests.py", "--min", "100"],
            cwd=ns.TEMPLATE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("100.0%", result.stdout)


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.created: list[Path] = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil
        for path in self.created:
            shutil.rmtree(path, ignore_errors=True)
            # Leave no empty category directory behind for the next run to trip over.
            parent = path.parent
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()

    def build(self, name="scaffold-probe", display="Scaffold Probe", category="utilities", **kw):
        target = ns.scaffold(name, display, category, **kw)
        self.created.append(target)
        return target

    def test_rejects_names_that_cannot_be_registry_identifiers(self):
        for bad in ("Bad Name", "-lead", "UPPER", "trailing-"):
            with self.subTest(name=bad), self.assertRaises(ns.ScaffoldError):
                ns.scaffold(bad, "X", "utilities")

    def test_rejects_a_category_the_schema_does_not_know(self):
        with self.assertRaises(ns.ScaffoldError):
            ns.scaffold("probe", "Probe", "quantum")

    def test_refuses_to_overwrite_without_force(self):
        target = self.build()
        with self.assertRaisesRegex(ns.ScaffoldError, "already exists"):
            ns.scaffold("scaffold-probe", "Scaffold Probe", "utilities")
        marker = target / "MARKER"
        marker.write_text("x", encoding="utf-8")
        self.build(force=True)
        self.assertFalse(marker.exists())

    def test_missing_template_is_reported(self):
        with mock.patch.object(ns, "TEMPLATE", Path("/nonexistent")):
            with self.assertRaisesRegex(ns.ScaffoldError, "template is missing"):
                ns.scaffold("probe", "Probe", "utilities")

    def test_module_and_cli_are_renamed_everywhere(self):
        target = self.build(name="my-tool", display="My Tool")
        self.assertTrue((target / "src" / "my_tool" / "core.py").is_file())
        for path in target.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".sh", ".md", ".json"}:
                text = path.read_text("utf-8")
                self.assertNotIn("example_skill", text, path.name)
                self.assertNotIn("example-skill", text, path.name)
                self.assertNotIn("Example Skill", text, path.name)
        installer = (target / "install.sh").read_text("utf-8")
        self.assertIn("MY_TOOL_PREFIX", installer)

    def test_executable_bits_survive_the_copy(self):
        target = self.build()
        for script in ("install.sh", "uninstall.sh"):
            self.assertTrue((target / script).stat().st_mode & 0o111, script)

    def test_manifest_is_reset_to_the_new_skill_and_marked_todo(self):
        target = self.build(name="fresh-start", display="Fresh Start", category="testing")
        manifest = json.loads((target / "skill.json").read_text("utf-8"))
        self.assertEqual(manifest["name"], "fresh-start")
        self.assertEqual(manifest["displayName"], "Fresh Start")
        self.assertEqual(manifest["category"], "testing")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["quality"], "experimental")
        self.assertIn("TODO", manifest["description"])

    def test_scaffolded_skill_validates_and_its_tests_pass(self):
        target = self.build(name="scaffold-probe", display="Scaffold Probe")
        manifest = json.loads((target / "skill.json").read_text("utf-8"))
        schema = json.loads(vs.SCHEMA_PATH.read_text("utf-8"))
        self.assertEqual(vs.validate(manifest, schema, "scaffolded"), [])
        # Layout complains only about the workflow the author still has to add.
        layout = vs.check_layout(manifest, target / "skill.json")
        self.assertEqual(layout, [f"skills/utilities/scaffold-probe: CI workflow "
                                  f".github/workflows/scaffold-probe-tests.yml does not exist"])
        result = subprocess.run(
            [sys.executable, "tests/run_tests.py", "--min", "100"],
            cwd=target, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_cli_reports_the_created_path(self):
        import io
        from contextlib import redirect_stdout
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = ns.main(["--name", "cli-probe", "--display", "CLI Probe", "--category", "utilities"])
        self.created.append(ns.SKILLS / "utilities" / "cli-probe")
        self.assertEqual(code, 0)
        self.assertIn("skills/utilities/cli-probe", buffer.getvalue())

    def test_cli_reports_a_bad_request_without_a_traceback(self):
        import io
        from contextlib import redirect_stderr
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            code = ns.main(["--name", "Bad Name", "--display", "X", "--category", "utilities"])
        self.assertEqual(code, ns.EXIT_ERROR)
        self.assertIn("not a valid skill name", buffer.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
