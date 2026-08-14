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
        self.assertIn(f"<b>{len(registry)}</b><span>skills</span>", self.index)
        self.assertIn(f"<b>{total}</b><span>tests passing</span>", self.index)

    def test_detail_pages_state_the_security_surface(self):
        page = self.files["skills/rangate.html"]
        for expected in ("Network access", "Credentials", "Irreversible operations",
                         "Independently reviewed", "Checksum", "sha256:"):
            self.assertIn(expected, page)

    def test_pages_reference_only_files_the_site_contains(self):
        available = set(self.files) | set(bs.binary_files())
        for name, content in self.files.items():
            if not name.endswith(".html"):
                continue
            base = Path(name).parent
            for reference in re.findall(r'(?:href|src)="(?!https?:|#|mailto:)([^"]+)"', content):
                target = reference.split("#")[0]
                if not target:
                    continue  # a link to a fragment on the same page
                resolved = os.path.normpath(os.path.join(str(base), target)).replace(os.sep, "/")
                with self.subTest(page=name, reference=reference):
                    self.assertIn(resolved, available)

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
        # The page's own <script> block is expected; nothing from the manifest is.
        self.assertNotIn("<script>alert", rendered)
        self.assertNotIn("<img src=x", rendered)
        self.assertNotIn('onerror="alert', rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&quot;", rendered)

    def test_the_embedded_json_cannot_close_its_own_script_tag(self):
        with mock.patch.object(bs, "load_registry", return_value=[skill(description="</script><script>x")]):
            with mock.patch.object(bs, "load_manifest", return_value={}):
                index = bs.build_index(bs.load_registry(), {"example": {}}, {})
        blob = re.search(r'id="skill-data">(.*?)</script>', index, re.S).group(1)
        self.assertIn("<\\/script>", blob)
        json.loads(blob)


class DiscoveryTests(unittest.TestCase):
    """Phase 5's discovery surface: history, maintainers, keywords, install counts."""

    def setUp(self):
        self.files = bs.render()
        self.index = self.files["index.html"]

    def test_recently_updated_is_ordered_by_release_date(self):
        history = bs.load_history()
        expected = sorted(history, key=lambda name: history[name]["released"] or "", reverse=True)
        section = self.index[self.index.index("Recently updated"):]
        order = [name for name in expected if f'skills/{name}.html' in section]
        self.assertEqual(order, expected)

    def test_detail_pages_carry_the_version_timeline(self):
        history = bs.load_history()
        for name, entry in history.items():
            page = self.files[f"skills/{name}.html"]
            with self.subTest(skill=name):
                self.assertIn("Version history", page)
                for item in entry["versions"]:
                    self.assertIn(f"v{item['version']}", page)
                    self.assertIn(item["date"][:10], page)
                self.assertIn(f"/commits/main/{bs.load_registry()[0]['path'].rsplit('/', 2)[0]}", page)

    def test_every_maintainer_has_a_page_listing_their_skills(self):
        manifests = {str(s["name"]): bs.load_manifest(s) for s in bs.load_registry()}
        people = bs.maintainer_index(manifests)
        self.assertTrue(people)
        self.assertIn("maintainers/index.html", self.files)
        for handle, person in people.items():
            page = self.files[f"maintainers/{handle}.html"]
            with self.subTest(maintainer=handle):
                self.assertIn(f"https://github.com/{handle}", page)
                for skill in person["skills"]:
                    self.assertIn(f"../skills/{skill}.html", page)

    def test_the_brand_mark_and_favicon_are_the_rendered_tile(self):
        index = self.files["index.html"]
        self.assertIn('href="assets/img/favicon.png"', index)
        self.assertIn('src="assets/img/icon-quarry.webp"', index)
        for name in ("assets/img/favicon.png", "assets/img/icon-quarry.webp"):
            self.assertIn(name, bs.binary_files())

    def test_skills_link_back_to_their_maintainer(self):
        page = self.files["skills/strata.html"]
        self.assertIn("../maintainers/BEKO2210.html", page)

    def test_keyword_cloud_offers_real_keywords(self):
        manifests = {str(s["name"]): bs.load_manifest(s) for s in bs.load_registry()}
        keywords = {k for m in manifests.values() for k in m.get("keywords") or []}
        rendered = bs.keyword_cloud(manifests)
        self.assertTrue(any(f'data-keyword="{word}"' in rendered for word in keywords))

    def test_every_skill_has_a_place_for_its_download_count(self):
        for entry in bs.load_registry():
            with self.subTest(skill=entry["name"]):
                self.assertIn(f'data-installs="{entry["name"]}"', self.index)
                self.assertIn(f'data-installs="{entry["name"]}"', self.files[f"skills/{entry['name']}.html"])

    def test_the_only_external_call_is_the_public_release_api(self):
        calls = re.findall(r"fetch\('([^']+)'\)", self.index + self.files["skills/strata.html"])
        self.assertTrue(calls)
        for url in calls:
            self.assertEqual(url, "https://api.github.com/repos/BEKO2210/SkillQuarry/releases")

    def test_motion_is_optional_and_respects_the_reader(self):
        self.assertIn("prefers-reduced-motion", self.files["style.css"])
        for name in ("index.html", "skills/strata.html", "maintainers/index.html"):
            page = self.files[name]
            with self.subTest(page=name):
                self.assertIn("prefers-reduced-motion", page)
                self.assertIn("IntersectionObserver", page)

    def test_artwork_falls_back_when_a_skill_has_none(self):
        """A skill added tomorrow carries no image; the card must still look intentional."""
        bare = {"name": "future-skill"}
        rendered = bs.artwork_for({}, bare)
        self.assertIn("linear-gradient", rendered)
        self.assertNotIn("<img", rendered)
        with_icon = bs.artwork_for({"icon": "../../../assets/strata-logo.svg"}, bare)
        self.assertIn("assets/strata-logo.svg", with_icon)
        self.assertIn("linear-gradient", with_icon)
        missing_file = bs.artwork_for({"image": "assets/img/does-not-exist.webp"}, bare)
        self.assertNotIn("does-not-exist", missing_file)

    def test_gradient_fallback_is_deterministic(self):
        self.assertEqual(bs.gradient_for("alpha"), bs.gradient_for("alpha"))
        self.assertNotEqual(bs.gradient_for("alpha"), bs.gradient_for("beta"))

    def test_real_images_are_used_where_a_manifest_declares_one(self):
        for entry in bs.load_registry():
            manifest = bs.load_manifest(entry)
            if not manifest.get("image"):
                continue
            with self.subTest(skill=entry["name"]):
                self.assertIn(manifest["image"], self.index)
                self.assertIn(manifest["image"], bs.binary_files())

    def test_the_hero_image_is_shipped_in_both_sizes(self):
        for name in ("assets/img/hero-1280.webp", "assets/img/hero-2400.webp"):
            self.assertIn(name, bs.binary_files())
        self.assertIn("assets/img/hero-2400.webp", self.index)

    @staticmethod
    def mp4_dimensions(blob: bytes) -> tuple[int, int]:
        """Read the coded width/height straight out of the MP4 sample entry.

        Parsing 8 bytes ourselves beats depending on ffprobe, which is not
        installed on a clean CI runner — and the rule "4K only" is worth a test
        that always runs.
        """
        # `avc1` also appears in the ftyp brand list, so start from the sample
        # description box; the first entry after it is the real one.
        table = blob.find(b"stsd")
        marker = blob.find(b"avc1", table) if table >= 0 else -1
        if marker < 0:
            raise AssertionError("no H.264 sample entry found in the hero video")
        import struct
        width, height = struct.unpack(">HH", blob[marker + 28:marker + 32])
        return width, height

    def test_the_hero_video_is_4k_and_loads_only_where_it_belongs(self):
        blobs = bs.binary_files()
        self.assertIn("assets/video/hero-4k.mp4", blobs)
        video = blobs["assets/video/hero-4k.mp4"]
        size_mb = len(video) / 1024 / 1024
        self.assertLess(size_mb, 15, f"hero video is {size_mb:.1f} MB")
        self.assertEqual(self.mp4_dimensions(video), (3840, 2160), "the hero video must be true 4K")
        index = self.index
        self.assertIn('preload="none"', index)
        self.assertIn("prefers-reduced-motion", index)
        self.assertIn("saveData", index)
        self.assertNotIn("min-width: 900px", index)  # phones get the video too
        self.assertIn('poster="assets/img/hero-2400.webp"', index)

    def test_the_typeface_is_shipped_not_borrowed(self):
        style = self.files["style.css"]
        self.assertIn("@font-face", style)
        self.assertIn('url("assets/fonts/InterVariable.woff2")', style)
        self.assertIn("font-display: swap", style)
        self.assertIn("assets/fonts/InterVariable.woff2", bs.binary_files())
        self.assertIn("assets/fonts/Inter-LICENSE.txt", bs.binary_files())
        # A missing font must never leave the page blank or reach for a CDN.
        self.assertNotIn("fonts.googleapis", style)
        self.assertIn("Segoe UI", style)

    def test_the_hero_video_is_actually_fetched(self):
        """preload="none" fetches nothing until asked, so the script has to ask."""
        index = self.files["index.html"]
        self.assertIn("video.load()", index)
        self.assertIn("loadeddata", index)

    def test_link_previews_have_an_image(self):
        for name in ("index.html", "skills/strata.html"):
            self.assertIn('property="og:image"', self.files[name])

    def test_each_card_shows_the_skill_mark(self):
        for entry in bs.load_registry():
            name = str(entry["name"])
            manifest = bs.load_manifest(entry)
            icon = bs.icon_for(manifest, name=name)
            with self.subTest(skill=name):
                self.assertIsNotNone(icon)
                self.assertIn(icon, self.files["index.html"])
                self.assertIn(icon, {**self.files, **bs.binary_files()})

    def test_the_rendered_mark_wins_over_the_flat_one(self):
        """3D tile when it exists, SVG when it does not, nothing when neither."""
        manifest = {"icon": "../../../assets/strata-logo.svg"}
        self.assertEqual(bs.icon_for(manifest, name="strata"), "assets/img/icon-strata.webp")
        self.assertEqual(bs.icon_for(manifest, name="no-such-skill"), "assets/strata-logo.svg")
        self.assertIsNone(bs.icon_for({}, name="no-such-skill"))
        self.assertEqual(bs.icon_for(manifest, depth=1, name="strata"), "../assets/img/icon-strata.webp")

    def test_the_page_still_works_when_that_call_fails(self):
        for page in (self.index, self.files["skills/strata.html"]):
            self.assertIn("catch", page)

    def test_the_contribution_call_to_action_points_at_real_places(self):
        for target in ("CONTRIBUTING.md", "docs/SKILL-SPEC.md", "issues/new/choose", "discussions"):
            self.assertIn(target, self.index)


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

    def test_a_missing_history_file_is_reported(self):
        with mock.patch.object(bs, "HISTORY", Path("/nonexistent/history.json")):
            with self.assertRaisesRegex(bs.SiteError, "build_history"):
                bs.load_history()

    def test_a_malformed_history_file_is_reported(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write("{ not json")
            broken = Path(handle.name)
        self.addCleanup(broken.unlink)
        with mock.patch.object(bs, "HISTORY", broken):
            with self.assertRaisesRegex(bs.SiteError, "cannot read"):
                bs.load_history()
        broken.write_text('{"schema_version": 1}', encoding="utf-8")
        with mock.patch.object(bs, "HISTORY", broken):
            with self.assertRaisesRegex(bs.SiteError, "no skills object"):
                bs.load_history()


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
