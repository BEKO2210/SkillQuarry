#!/usr/bin/env python3
"""Tests for the README/registry generator. Standard library only.

    python3 tools/test_render_readme.py
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render_readme as rr


def manifest(**overrides):
    base = {
        "name": "example",
        "displayName": "Example",
        "version": "1.0.0",
        "description": "Does something useful.",
        "category": "utilities",
        "license": "Apache-2.0",
        "_dir": "skills/utilities/example",
    }
    base.update(overrides)
    return base


class DiscoveryTests(unittest.TestCase):
    def test_repository_manifests_are_complete(self):
        found = rr.discover_manifests()
        self.assertTrue(found, "the repository must ship at least one skill")
        for item in found:
            for field in rr.REQUIRED_FIELDS:
                self.assertTrue(item.get(field), f"{item['_dir']} is missing {field}")

    def test_manifests_are_sorted_by_category_then_name(self):
        found = rr.discover_manifests()
        keys = [(item["category"], item["name"]) for item in found]
        self.assertEqual(keys, sorted(keys))

    def test_broken_manifest_is_reported_not_guessed(self):
        with mock.patch.object(rr, "SKILLS_DIR", Path("/nonexistent")):
            with self.assertRaises(rr.ManifestError):
                rr.discover_manifests()

    def test_every_manifest_path_referenced_in_the_readme_exists(self):
        for item in rr.discover_manifests():
            directory = rr.REPO / item["_dir"]
            self.assertTrue((directory / "README.md").exists(), f"{item['_dir']}/README.md")
            self.assertTrue((directory / "SKILL.md").exists(), f"{item['_dir']}/SKILL.md")
            report = rr._tests(item).get("report")
            if report:
                self.assertTrue((directory / report).exists(), f"{item['_dir']}/{report}")
            banner = item.get("banner")
            if banner:
                self.assertTrue((rr.REPO / banner).exists(), banner)


class RenderTests(unittest.TestCase):
    def test_table_row_is_escaped_free_of_newlines(self):
        table = rr.render_table([manifest()])
        self.assertEqual(len(table.splitlines()), 3)
        self.assertIn("skills/utilities/example", table)

    def test_unknown_category_and_agent_fall_back_to_their_raw_value(self):
        rendered = rr.render_table([manifest(category="quantum", agents=["future-agent"])])
        self.assertIn("Quantum", rendered)
        self.assertIn("future-agent", rendered)

    def test_stats_sum_test_counts(self):
        stats = rr.render_stats([
            manifest(tests={"count": 10}),
            manifest(name="other", category="security", tests={"count": 5}),
        ])
        self.assertIn("tests-15%20passing", stats)
        self.assertIn("skills-2", stats)

    def test_ci_badge_defaults_to_the_skill_workflow_name(self):
        self.assertIn("example-tests.yml", rr.render_ci([manifest()]))
        self.assertIn("custom.yml", rr.render_ci([manifest(workflow="custom.yml")]))

    def test_card_survives_a_minimal_manifest(self):
        card = rr.render_cards([manifest()])
        self.assertIn("### Example", card)
        self.assertIn("[Documentation](skills/utilities/example/README.md)", card)

    def test_registry_is_deterministic(self):
        first = rr.render_registry(rr.discover_manifests())
        second = rr.render_registry(rr.discover_manifests())
        self.assertEqual(first, second)
        json.loads(first)

    def test_missing_markers_are_an_error(self):
        with self.assertRaises(rr.ManifestError):
            rr.replace_block("no markers here", "SKILLS:TABLE", "x")

    def test_replace_block_only_touches_its_own_block(self):
        text = "head <!-- A:START -->old<!-- A:END --> tail"
        self.assertEqual(
            rr.replace_block(text, "A", "new"),
            "head <!-- A:START -->\nnew\n<!-- A:END --> tail",
        )


class CheckModeTests(unittest.TestCase):
    def test_repository_is_currently_in_sync(self):
        self.assertEqual(rr.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
