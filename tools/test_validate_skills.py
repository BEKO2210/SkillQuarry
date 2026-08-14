#!/usr/bin/env python3
"""Tests for the manifest validator, including the cases it must reject.

    python3 tools/test_validate_skills.py
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_skills as vs

SCHEMA = json.loads(vs.SCHEMA_PATH.read_text("utf-8"))


def valid_manifest(**overrides):
    base = {
        "name": "example",
        "displayName": "Example",
        "version": "1.0.0",
        "description": "A reusable capability that does one clearly described thing.",
        "category": "utilities",
        "license": "Apache-2.0",
    }
    base.update(overrides)
    return base


class SchemaEngineTests(unittest.TestCase):
    def check(self, manifest):
        return vs.validate(manifest, SCHEMA, "test")

    def test_minimal_valid_manifest_passes(self):
        self.assertEqual(self.check(valid_manifest()), [])

    def test_missing_required_field_is_named(self):
        manifest = valid_manifest()
        del manifest["license"]
        self.assertIn("missing required field 'license'", " ".join(self.check(manifest)))

    def test_unknown_field_is_rejected(self):
        errors = self.check(valid_manifest(surprise=True))
        self.assertIn("unknown field 'surprise'", " ".join(errors))

    def test_extensions_namespace_is_the_escape_hatch(self):
        self.assertEqual(self.check(valid_manifest(extensions={"anything": 1})), [])

    def test_name_must_be_a_registry_slug(self):
        for bad in ("Example", "ex ample", "-example", "e", "example--x"):
            with self.subTest(name=bad):
                self.assertTrue(self.check(valid_manifest(name=bad)))

    def test_version_must_be_semver(self):
        self.assertEqual(self.check(valid_manifest(version="1.2.3-rc.1")), [])
        for bad in ("1.0", "v1.0.0", "01.0.0", "next"):
            with self.subTest(version=bad):
                self.assertTrue(self.check(valid_manifest(version=bad)))

    def test_category_is_a_closed_set(self):
        self.assertTrue(self.check(valid_manifest(category="quantum")))

    def test_quality_is_a_closed_set(self):
        self.assertEqual(self.check(valid_manifest(quality="tested")), [])
        self.assertTrue(self.check(valid_manifest(quality="awesome")))

    def test_wrong_types_are_reported_not_coerced(self):
        self.assertTrue(self.check(valid_manifest(keywords="git")))
        self.assertTrue(self.check(valid_manifest(tests={"command": "run", "count": "many"})))
        self.assertTrue(self.check(valid_manifest(tests={"command": "run", "count": True})))

    def test_nested_object_rules_apply(self):
        self.assertTrue(self.check(valid_manifest(tests={"count": 3})))  # command is required
        self.assertTrue(self.check(valid_manifest(entrypoints={"unknown": "x"})))
        self.assertEqual(self.check(valid_manifest(tests={"command": "python3 -m unittest"})), [])

    def test_array_bounds_and_uniqueness(self):
        self.assertTrue(self.check(valid_manifest(platforms=["linux", "linux"])))
        self.assertTrue(self.check(valid_manifest(platforms=["solaris"])))
        self.assertEqual(self.check(valid_manifest(platforms=["linux", "macos"])), [])

    def test_string_length_bounds(self):
        self.assertTrue(self.check(valid_manifest(description="too short")))
        self.assertTrue(self.check(valid_manifest(tagline="x" * 200)))

    def test_unsupported_schema_keyword_fails_loudly(self):
        errors = vs.validate({}, {"type": "object", "oneOf": []}, "test")
        self.assertIn("unsupported keywords: oneOf", errors[0])

    def test_top_level_type_mismatch_short_circuits(self):
        self.assertEqual(vs.validate([], SCHEMA, "test"), ["test: expected object, found list"])


class LayoutTests(unittest.TestCase):
    def test_repository_manifests_pass_the_layout_rules(self):
        for path in sorted(vs.SKILLS_DIR.glob("*/*/skill.json")):
            manifest = json.loads(path.read_text("utf-8"))
            with self.subTest(skill=path.parent.name):
                self.assertEqual(vs.check_layout(manifest, path), [])

    def test_name_must_match_its_directory(self):
        path = vs.SKILLS_DIR / "utilities" / "example" / "skill.json"
        errors = vs.check_layout(valid_manifest(name="mismatch"), path)
        self.assertIn("does not match the directory name", " ".join(errors))

    def test_category_must_match_its_directory(self):
        path = vs.SKILLS_DIR / "utilities" / "example" / "skill.json"
        errors = vs.check_layout(valid_manifest(category="security"), path)
        self.assertIn("does not match the directory", " ".join(errors))

    def test_missing_referenced_files_are_reported(self):
        path = vs.SKILLS_DIR / "utilities" / "example" / "skill.json"
        errors = " ".join(vs.check_layout(
            valid_manifest(
                banner="assets/nope.svg",
                research="NOPE.md",
                entrypoints={"skill": "SKILL.md", "install": "install.sh"},
                tests={"command": "x", "report": "TEST_REPORT.md"},
            ),
            path,
        ))
        for expected in ("banner", "research", "entrypoints.install", "tests.report", "CI workflow", "README.md"):
            self.assertIn(expected, errors)


class EndToEndTests(unittest.TestCase):
    def test_repository_validates(self):
        self.assertEqual(vs.main([]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
