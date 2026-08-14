#!/usr/bin/env python3
"""Tests for the static marketplace generator.

    python3 tools/test_build_site.py
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_site as bs


def skill(**overrides):
    base = {
        "name": "example", "displayName": "Example", "version": "1.0.0",
        "description": "Does one thing.", "category": "utilities", "license": "Apache-2.0",
        "path": "skills/utilities/example", "compatibility": ["claude-code"],
        "platforms": ["linux"], "quality": "tested", "keywords": ["counting"],
        "checksum": "sha256:abc",
        "security": {"network_access": "none", "requires_secrets": False,
                     "runs_external_commands": False, "writes_outside_repository": False},
        "tests": {"count": 5, "coverage": "100%", "report": "TEST_REPORT.md"},
        "requires": {"binaries": []},
    }
    base.update(overrides)
    return base


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.files = bs.render()
        self.index = self.files["index.html"]

    def test_every_skill_has_a_card_and_a_page(self):
        for entry in bs.load_registry():
            name = entry["name"]
            with self.subTest(skill=name):
                self.assertIn(f'data-name="{name}"', self.index)
                self.assertIn(f"skills/{name}.html", self.files)

    def test_the_index_carries_the_data_the_filters_need(self):
        blob = re.search(r'<script type="application/json" id="skill-data">(.*?)</script>',
                         self.index, re.S).group(1)
        data = json.loads(blob)
        self.assertEqual({item["name"] for item in data},
                         {item["name"] for item in bs.load_registry()})
        for item in data:
            self.assertIn("security", item)
            self.assertIn("compatibility", item)

    def test_counts_shown_match_the_registry(self):
        registry = bs.load_registry()
        total = sum(int((s.get("tests") or {}).get("count") or 0) for s in registry)
        self.assertIn(f"<b>{len(registry)}</b> skills", self.index)
        self.assertIn(f"<b>{total}</b> tests passing", self.index)

    def test_detail_pages_state_the_security_surface(self):
        page = self.files["skills/rangate.html"]
        for expected in ("Network access", "Credentials", "Irreversible operations",
                         "Independently reviewed", "Checksum", "sha256:"):
            self.assertIn(expected, page)

    def test_pages_reference_only_files_the_site_contains(self):
        for name, content in self.files.items():
            if not name.endswith(".html"):
                continue
            base = Path(name).parent
            for reference in re.findall(r'(?:href|src)="(?!https?:|#|mailto:)([^"]+)"', content):
                resolved = os.path.normpath(os.path.join(str(base), reference)).replace(os.sep, "/")
                with self.subTest(page=name, reference=reference):
                    self.assertIn(resolved, self.files)

    def test_nothing_is_loaded_from_a_third_party(self):
        for name, content in self.files.items():
            if not name.endswith((".html", ".css")):
                continue
            for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', content):
                with self.subTest(page=name, url=url):
                    self.assertTrue(url.startswith("https://github.com/"), url)
            self.assertNotIn("@import", content)

    def test_the_site_is_deterministic(self):
        self.assertEqual(bs.render(), self.files)

    def test_assets_are_copied(self):
        self.assertIn("assets/skillquarry-banner.svg", self.files)
        self.assertIn("<svg", self.files["assets/skillquarry-logo.svg"])


class EscapingTests(unittest.TestCase):
    def test_manifest_text_cannot_inject_markup(self):
        hostile = skill(displayName='<img src=x onerror="alert(1)">',
                        description="</p><script>alert(2)</script>")
        manifest = {"tagline": '"><script>alert(3)</script>', "highlights": ["<b>bold</b>"],
                    "quickstart": "echo '<script>'"}
        rendered = bs.card(hostile, manifest) + bs.build_detail(hostile, manifest)
        # Nothing dangerous survives as markup; the same characters as text are fine.
        self.assertNotIn("<script", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn('onerror="alert', rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&quot;", rendered)

    def test_the_embedded_json_cannot_close_its_own_script_tag(self):
        with mock.patch.object(bs, "load_registry", return_value=[skill(description="</script><script>x")]):
            with mock.patch.object(bs, "load_manifest", return_value={}):
                index = bs.build_index(bs.load_registry(), {"example": {}})
        blob = re.search(r'id="skill-data">(.*?)</script>', index, re.S).group(1)
        self.assertIn("<\\/script>", blob)
        json.loads(blob)


class FailureTests(unittest.TestCase):
    def test_a_missing_registry_is_reported(self):
        with mock.patch.object(bs, "REGISTRY", Path("/nonexistent/skills.json")):
            with self.assertRaisesRegex(bs.SiteError, "cannot read"):
                bs.load_registry()

    def test_an_empty_registry_is_refused(self):
        with mock.patch.object(bs, "load_registry", side_effect=bs.SiteError("registry has no skills")):
            buffer = io.StringIO()
            with redirect_stderr(buffer):
                self.assertEqual(bs.main([]), 2)
            self.assertIn("registry has no skills", buffer.getvalue())

    def test_a_missing_manifest_is_reported(self):
        with self.assertRaisesRegex(bs.SiteError, "cannot read"):
            bs.load_manifest({"name": "ghost", "path": "skills/none/ghost"})


class CheckModeTests(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = bs.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_the_committed_site_is_current(self):
        code, out, err = self.run_main("--check")
        self.assertEqual(code, 0, err)
        self.assertIn("up to date", out)

    def test_drift_is_named_by_file(self):
        stale = dict(bs.render())
        stale["index.html"] = "old"
        del stale["style.css"]
        stale["leftover.html"] = "x"
        with mock.patch.object(bs, "current", return_value=stale):
            code, _, err = self.run_main("--check")
        self.assertEqual(code, bs.EXIT_STALE)
        self.assertIn("stale: index.html", err)
        self.assertIn("missing: style.css", err)
        self.assertIn("unexpected: leftover.html", err)

    def test_an_absent_site_directory_counts_as_drift(self):
        with mock.patch.object(bs, "SITE", Path("/nonexistent/site")):
            self.assertEqual(bs.current(), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
