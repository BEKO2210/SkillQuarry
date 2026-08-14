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



class SecurityMetadataTests(unittest.TestCase):
    def test_a_skill_that_runs_commands_needs_a_security_block(self):
        manifest = valid_manifest(permissions={"shell": "spawns git"})
        errors = " ".join(vs.check_security(manifest, "skills/utilities/example/skill.json"))
        self.assertIn("`security` block is required", errors)

    def test_a_skill_without_a_shell_needs_nothing(self):
        self.assertEqual(vs.check_security(valid_manifest(permissions={"shell": "none"}), "x"), [])
        self.assertEqual(vs.check_security(valid_manifest(), "x"), [])

    def test_the_security_block_must_agree_with_the_permissions(self):
        manifest = valid_manifest(
            permissions={"shell": "spawns git"},
            security={"network_access": "none", "runs_external_commands": False,
                      "writes_outside_repository": False, "requires_secrets": False},
        )
        errors = " ".join(vs.check_security(manifest, "x"))
        self.assertIn("runs_external_commands is false", errors)

    def test_a_threat_model_file_that_does_not_exist_is_reported(self):
        manifest = valid_manifest(security={
            "network_access": "none", "runs_external_commands": False,
            "writes_outside_repository": False, "requires_secrets": False,
            "threat_model": "NOPE.md",
        })
        errors = " ".join(vs.check_security(manifest, "skills/utilities/example/skill.json"))
        self.assertIn("security.threat_model NOPE.md does not exist", errors)

    def test_every_repository_skill_declares_its_security_surface(self):
        for path in sorted(vs.SKILLS_DIR.glob("*/*/skill.json")):
            manifest = json.loads(path.read_text("utf-8"))
            with self.subTest(skill=path.parent.name):
                self.assertIn("security", manifest)
                self.assertEqual(vs.check_security(manifest, path.relative_to(vs.REPO).as_posix()), [])


class VersionConsistencyTests(unittest.TestCase):
    def test_repository_skills_agree_with_their_own_packaging(self):
        for path in sorted(vs.SKILLS_DIR.glob("*/*/skill.json")):
            manifest = json.loads(path.read_text("utf-8"))
            declared = vs.declared_versions(path.parent)
            for source, version in declared.items():
                with self.subTest(skill=path.parent.name, source=source):
                    self.assertEqual(version, manifest["version"])

    def test_a_disagreeing_version_is_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
            self.assertEqual(vs.declared_versions(directory), {"pyproject.toml": "9.9.9"})

    def test_a_skill_without_packaging_declares_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(vs.declared_versions(Path(tmp)), {})



class RelationTests(unittest.TestCase):
    """Dependencies decide install order, so a bad graph must never be published."""

    def graph(self, **skills):
        return {name: {"version": "1.0.0", **body} for name, body in skills.items()}

    def test_the_repository_graph_is_sound(self):
        self.assertEqual(vs.check_relations(vs.load_all_manifests()), [])

    def test_a_missing_dependency_is_named(self):
        errors = vs.check_relations(self.graph(a={"dependencies": [{"name": "ghost"}]}))
        self.assertIn("depends on 'ghost'", " ".join(errors))

    def test_a_self_dependency_is_rejected(self):
        errors = vs.check_relations(self.graph(a={"dependencies": [{"name": "a"}]}))
        self.assertIn("depends on itself", " ".join(errors))

    def test_a_cycle_is_reported_with_its_path(self):
        errors = vs.check_relations(self.graph(
            a={"dependencies": [{"name": "b"}]},
            b={"dependencies": [{"name": "a"}]},
        ))
        self.assertTrue(any("dependency cycle" in error for error in errors))

    def test_a_minimum_version_must_be_satisfiable(self):
        errors = vs.check_relations({
            "a": {"version": "1.0.0", "dependencies": [{"name": "b", "minimum_version": "2.0.0"}]},
            "b": {"version": "1.5.0"},
        })
        self.assertIn("needs b >= 2.0.0", " ".join(errors))
        self.assertEqual(vs.check_relations({
            "a": {"version": "1.0.0", "dependencies": [{"name": "b", "minimum_version": "1.0.0"}]},
            "b": {"version": "1.5.0"},
        }), [])

    def test_composes_with_must_name_real_skills(self):
        errors = vs.check_relations(self.graph(a={"composes_with": ["ghost"]}))
        self.assertIn("composes_with names 'ghost'", " ".join(errors))
        self.assertIn("itself", " ".join(vs.check_relations(self.graph(a={"composes_with": ["a"]}))))

    def test_install_order_puts_dependencies_first(self):
        graph = self.graph(
            app={"dependencies": [{"name": "lib"}]},
            lib={"dependencies": [{"name": "base"}]},
            base={},
        )
        self.assertEqual(vs.install_order(graph, "app"), ["base", "lib", "app"])

    def test_every_verification_states_who_when_how_and_what(self):
        for path in sorted(vs.SKILLS_DIR.glob("*/*/skill.json")):
            manifest = json.loads(path.read_text("utf-8"))
            for entry in manifest.get("verifications", []):
                with self.subTest(skill=path.parent.name):
                    for field in ("by", "date", "method", "result"):
                        self.assertTrue(entry.get(field), field)
                    self.assertIn(entry["result"], {"passed", "passed-with-findings", "failed"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
