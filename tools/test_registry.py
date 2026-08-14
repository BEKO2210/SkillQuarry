#!/usr/bin/env python3
"""Tests for the registry query/verify tool and for checksum behaviour.

    python3 tools/test_registry.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import registry as rg
import render_readme as rr


def entry(**overrides):
    base = {
        "name": "example",
        "displayName": "Example",
        "version": "1.0.0",
        "description": "Does one thing.",
        "category": "utilities",
        "path": "skills/utilities/example",
        "compatibility": ["claude-code"],
        "platforms": ["linux", "macos"],
        "quality": "tested",
        "keywords": ["counting"],
        "security": {"network_access": "none", "requires_secrets": False,
                     "runs_external_commands": False, "writes_outside_repository": False},
        "tests": {"count": 5, "coverage": "100%"},
    }
    base.update(overrides)
    return base


class ChecksumTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "run.sh").write_text("echo hi\n", encoding="utf-8")
        os.chmod(self.root / "run.sh", 0o755)

    def test_checksum_is_stable_and_prefixed(self):
        first = rr.skill_checksum(self.root)
        self.assertTrue(first.startswith("sha256:"))
        self.assertEqual(first, rr.skill_checksum(self.root))

    def test_content_change_changes_the_checksum(self):
        before = rr.skill_checksum(self.root)
        (self.root / "src" / "core.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.assertNotEqual(before, rr.skill_checksum(self.root))

    def test_rename_changes_the_checksum(self):
        before = rr.skill_checksum(self.root)
        (self.root / "src" / "core.py").rename(self.root / "src" / "main.py")
        self.assertNotEqual(before, rr.skill_checksum(self.root))

    def test_losing_the_executable_bit_changes_the_checksum(self):
        before = rr.skill_checksum(self.root)
        os.chmod(self.root / "run.sh", 0o644)
        self.assertNotEqual(before, rr.skill_checksum(self.root))

    def test_build_output_and_caches_are_ignored(self):
        before = rr.skill_checksum(self.root)
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "core.cpython-312.pyc").write_bytes(b"\x00\x01")
        (self.root / "target" / "debug").mkdir(parents=True)
        (self.root / "target" / "debug" / "artifact.rlib").write_bytes(b"\x02")
        self.assertEqual(before, rr.skill_checksum(self.root))


class FilterTests(unittest.TestCase):
    def match(self, skill, **filters):
        defaults = dict(agent=None, platform=None, category=None, quality=None,
                        offline=False, no_secrets=False, keyword=None)
        defaults.update(filters)
        return rg.matches(skill, **defaults)

    def test_no_filter_matches_everything(self):
        self.assertTrue(self.match(entry()))

    def test_agent_platform_category_and_quality(self):
        self.assertTrue(self.match(entry(), agent="claude-code"))
        self.assertFalse(self.match(entry(), agent="codex"))
        self.assertTrue(self.match(entry(), platform="linux"))
        self.assertFalse(self.match(entry(), platform="windows"))
        self.assertTrue(self.match(entry(), category="utilities"))
        self.assertFalse(self.match(entry(), category="security"))
        self.assertTrue(self.match(entry(), quality="tested"))
        self.assertFalse(self.match(entry(), quality="experimental"))

    def test_offline_filter_excludes_indirect_network_access(self):
        self.assertTrue(self.match(entry(), offline=True))
        indirect = entry(security={"network_access": "indirect", "requires_secrets": False})
        self.assertFalse(self.match(indirect, offline=True))

    def test_no_secrets_filter_requires_an_explicit_false(self):
        self.assertTrue(self.match(entry(), no_secrets=True))
        unknown = entry(security={"network_access": "none"})
        self.assertFalse(self.match(unknown, no_secrets=True))

    def test_keyword_searches_name_description_and_keywords(self):
        self.assertTrue(self.match(entry(), keyword="COUNT"))
        self.assertTrue(self.match(entry(), keyword="one thing"))
        self.assertFalse(self.match(entry(), keyword="kubernetes"))

    def test_missing_fields_never_count_as_a_match(self):
        self.assertFalse(self.match({"name": "bare"}, agent="claude-code"))
        self.assertFalse(self.match({"name": "bare"}, platform="linux"))


class VerifyTests(unittest.TestCase):
    def test_repository_registry_matches_the_files_on_disk(self):
        self.assertEqual(rg.verify(rg.load()), [])

    def test_a_changed_checksum_is_reported(self):
        skills = [dict(item) for item in rg.load()]
        skills[0]["checksum"] = "sha256:0000"
        problems = rg.verify(skills)
        self.assertEqual(len(problems), 1)
        self.assertIn("does not match the files on disk", problems[0])

    def test_a_missing_path_is_reported(self):
        problems = rg.verify([entry(path="skills/utilities/gone", checksum="sha256:0")])
        self.assertIn("does not exist", problems[0])


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = rg.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_list_prints_every_skill(self):
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        for name in ("strata", "cordon", "rangate"):
            self.assertIn(name, out)

    def test_list_json_is_machine_readable(self):
        code, out, _ = self.run_cli("list", "--json", "--category", "security")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload)
        self.assertTrue(all(item["category"] == "security" for item in payload))

    def test_filters_that_match_nothing_say_so(self):
        code, out, _ = self.run_cli("list", "--platform", "windows")
        self.assertEqual(code, 0)
        self.assertIn("no skill matches", out)

    def test_show_prints_one_entry_and_fails_on_an_unknown_name(self):
        code, out, _ = self.run_cli("show", "strata")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["name"], "strata")
        code, _, err = self.run_cli("show", "nope")
        self.assertEqual(code, rg.EXIT_ERROR)
        self.assertIn("no skill named", err)

    def test_verify_passes_on_the_repository(self):
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 0)
        self.assertIn("checksums match", out)

    def test_verify_fails_loudly_on_drift(self):
        original = rg.load()
        drifted = [dict(item) for item in original]
        drifted[0]["checksum"] = "sha256:0000"
        with mock.patch.object(rg, "load", return_value=drifted):
            code, _, err = self.run_cli("verify")
        self.assertEqual(code, rg.EXIT_MISMATCH)
        self.assertIn("render_readme.py", err)

    def test_an_unreadable_registry_is_reported_not_guessed(self):
        with mock.patch.object(rg, "REGISTRY", Path("/nonexistent/skills.json")):
            code, _, err = self.run_cli("list")
        self.assertEqual(code, rg.EXIT_ERROR)
        self.assertIn("cannot read", err)

    def test_a_registry_without_a_skills_array_is_reported(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write('{"schema_version": 2}')
            broken = Path(handle.name)
        self.addCleanup(broken.unlink)
        with mock.patch.object(rg, "REGISTRY", broken):
            with self.assertRaisesRegex(rg.RegistryError, "no skills array"):
                rg.load()


if __name__ == "__main__":
    unittest.main(verbosity=2)
