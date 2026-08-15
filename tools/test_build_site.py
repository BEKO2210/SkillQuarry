#!/usr/bin/env python3
"""Tests for the static marketplace generator.

    python3 tools/test_build_site.py
"""

from __future__ import annotations

import ast
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
                target = reference.split("#")[0].split("?")[0]
                if not target:
                    continue  # a link to a fragment on the same page
                resolved = os.path.normpath(os.path.join(str(base), target)).replace(os.sep, "/")
                with self.subTest(page=name, reference=reference):
                    self.assertIn(resolved, available)

    # Sites a link may point at. Linking loads nothing; it is a citation, and
    # naming the tools this project runs on requires being able to point at them.
    LINKABLE = ("https://github.com/", "https://www.rust-lang.org", "https://www.python.org")

    def test_nothing_is_loaded_from_a_third_party(self):
        """No byte on this page may come from a host other than its own.

        Loading and linking are different risks and are checked differently: a
        `src` fetches code or an image at render time, a `href` is a citation
        the reader chooses to follow.
        """
        for name, content in self.files.items():
            if not name.endswith((".html", ".css")):
                continue
            for url in re.findall(r'(?:src|poster)="(https?://[^"]+)"', content):
                with self.subTest(page=name, loaded=url):
                    self.fail(f"{name} loads {url} from another host")
            for url in re.findall(r'<link[^>]+href="(https?://[^"]+)"', content):
                with self.subTest(page=name, linked_stylesheet=url):
                    self.fail(f"{name} pulls {url} into the page")
            for url in re.findall(r'<a[^>]+href="(https?://[^"]+)"', content):
                with self.subTest(page=name, url=url):
                    self.assertTrue(url.startswith(self.LINKABLE), url)
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
        # A forward seamless loop: generated with its first frame as its own end
        # state, then the tail crossfaded into the head. A palindrome was tried
        # first and rejected — the direction reversal at each end reads as a
        # restart even when no frame jumps.
        self.assertGreater(len(video), 4 * 1024 * 1024, "suspiciously small for a 4K loop")
        self.assertEqual(self.mp4_dimensions(video), (3840, 2160), "the hero video must be true 4K")
        index = self.index
        self.assertIn('preload="none"', index)
        self.assertIn("prefers-reduced-motion", index)
        self.assertIn("saveData", index)
        self.assertNotIn("min-width: 900px", index)  # phones get the video too
        self.assertIn('poster="assets/img/hero-2400.webp"', index)
        # The video URL carries a fingerprint of the file, so replacing the loop
        # replaces it on phones that cached the previous one.
        self.assertRegex(index, r"hero-4k\.mp4\?v=[0-9a-f]{10}")
        import hashlib
        expected = hashlib.sha256(blobs["assets/video/hero-4k.mp4"]).hexdigest()[:10]
        self.assertIn(f"hero-4k.mp4?v={expected}", index)

    def test_the_site_shows_how_to_install_without_a_checkout(self):
        """A visitor must be able to install from the page alone.

        The site used to print `git clone` and nothing else, while the client can
        install straight from the published registry. Someone who only reads the
        page would never learn that.
        """
        index = self.files["index.html"]
        self.assertIn(bs.CLIENT_URL, index)
        self.assertIn(f"export SKILLQUARRY_REGISTRY={bs.REGISTRY_URL}", index)
        self.assertIn('id="install"', index)
        # The hero button points at that section, not at a heading on another
        # site that may not exist.
        self.assertIn('href="#install"', index)
        self.assertNotIn("#install-the-client", index)
        # Every skill page names its own install command against the registry.
        for skill in bs.load_registry():
            page = self.files[f"skills/{skill['name']}.html"]
            self.assertIn(bs.REGISTRY_URL, page)
            self.assertIn(f"skillquarry install {skill['name']} --prefix", page)
            self.assertIn(f"skillquarry uninstall {skill['name']}", page)

    def test_the_published_addresses_follow_the_repository(self):
        """A fork must not advertise this repository's registry."""
        self.assertEqual(bs.REGISTRY_URL, f"{bs.PAGES_URL}/api/v1/skills.json")
        self.assertIn(bs.REPO_SLUG, bs.CLIENT_URL)
        served = json.loads(self.files[".well-known/skillquarry.json"])
        self.assertEqual(served["registry"], bs.REGISTRY_URL)

    def test_the_dependency_claim_is_about_the_client_and_is_true(self):
        """The hero used to say "No dependencies" for the whole marketplace.

        That stopped being true when a skill shipped pinned parsers. The claim
        now names what it covers — the client — and this test checks the claim
        against the client's own imports instead of trusting the sentence.
        """
        self.assertIn("client dependencies", self.index)
        self.assertNotIn("<span>dependencies</span>", self.index)

        source = (bs.REPO / "cli" / "skillquarry.py").read_text("utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        third_party = imported - set(sys.stdlib_module_names)
        self.assertEqual(third_party, set(), f"the client imports {third_party}")

    def test_a_skill_is_marked_verified_only_when_someone_verified_it(self):
        for entry in bs.load_registry():
            page_tag = f'data-name="{entry["name"]}"'
            card = self.index.split(page_tag)[1].split("</article>")[0]
            claimed = "&#10003; verified" in card
            recorded = bool(bs.verified_by(entry))
            self.assertEqual(claimed, recorded, f"{entry['name']}: badge and manifest disagree")

    def test_the_wall_shows_every_published_skill(self):
        """The point of the wall: publish a skill, it appears. No page edited."""
        for entry in bs.load_registry():
            with self.subTest(skill=entry["name"]):
                self.assertIn(f'class="wall-tile" href="skills/{entry["name"]}.html"', self.index)
        self.assertEqual(self.index.count('class="wall-tile"'), len(bs.load_registry()))

    def test_the_built_with_marks_are_embedded_not_fetched(self):
        for _, slug, _, _ in bs.BUILT_WITH:
            mark = (bs.ASSETS / "brand" / f"{slug}.svg").read_text("utf-8")
            path = mark.split('<path d="')[1].split('"')[0][:40]
            with self.subTest(mark=slug):
                self.assertIn(path, self.index, f"{slug} is not inlined")

    def test_the_built_with_row_claims_no_endorsement(self):
        """These projects do not sponsor this one, and their trademark policies
        forbid implying they do. The page has to say so, in the page."""
        self.assertIn("not to suggest any endorsement or sponsorship", self.index)
        for word in ("sponsored by", "in partnership with", "supported by"):
            self.assertNotIn(word, self.index.lower())

    def test_the_recent_releases_are_a_rail_that_does_not_move_by_itself(self):
        """Motion the reader did not ask for is a known usability defect.

        Nielsen Norman's study of auto-forwarding content found users miss the
        largest element on a page when it rotates, and WCAG 2.2.2 requires a way
        to stop motion that runs longer than five seconds. This rail scrolls
        only when someone scrolls it, so there is nothing to pause — and this
        test fails if an interval or animation is ever added to it.
        """
        self.assertIn('class="rail"', self.index)
        self.assertIn('data-rail="next"', self.index)
        rail_script = self.index.split("The rail moves only")[1].split("// The keyword tail")[0]
        for forbidden in ("setInterval", "setTimeout", "requestAnimationFrame"):
            self.assertNotIn(forbidden, rail_script, "the rail must not move on its own")

    def test_the_fold_control_does_not_filter_anything(self):
        """It shares a list with the keyword buttons; it must not share their job."""
        self.assertIn(".cloud button[data-keyword]", self.index)
        more = self.index.split("data-cloud-more")[1].split("</li>")[0]
        self.assertNotIn("data-keyword", more)

    def test_the_keyword_head_is_filled_and_the_tail_is_folded(self):
        cloud = self.index.split('<ul class="cloud">')[1].split("</ul>")[0]
        shown = cloud.count("<li>")
        folded = cloud.count("data-tail")
        self.assertGreaterEqual(shown, 8, "the visible head is too short to be useful")
        self.assertGreater(folded, 0, "nothing is folded, so the control is pointless")
        self.assertIn("more</button>", cloud)

    def css_rules(self):
        """Every `selector { body }` pair of the stylesheet, at-rules aside."""
        return [
            (sel.strip(), body)
            for sel, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", bs.STYLE)
        ]

    def css_rule(self, pattern):
        """The first rule matching `pattern`, as written."""
        found = re.search(pattern, bs.STYLE)
        self.assertIsNotNone(found, f"no rule matched {pattern}")
        return found.group(0)

    def test_card_text_keeps_its_distance_from_the_edge(self):
        """The inset must live on the card itself.

        It used to live on the children (`.card > *:not(.art)`), and a later,
        more specific rule — `.card p.body { margin: 0 }` — silently won, so the
        description of every skill touched the tile border on a phone. Nothing in
        the test suite noticed, because the rule that was supposed to create the
        gap was still there. Pinning the card's own padding removes that class of
        failure: a child cannot reset a padding it does not own.
        """
        card = self.css_rule(r"\.card\s*\{[^}]*padding[^}]*\}")
        self.assertIn("padding: 0 var(--s4) var(--s4)", card)
        # The picture is the one child allowed to reach the edge.
        self.assertIn(".card > .art { margin: 0 calc(-1 * var(--s4)); }", bs.STYLE)
        # No rule inside a card may create the gap with a horizontal margin
        # again — that is what made the previous version fragile.
        for selector, body in self.css_rules():
            if ".card" in selector and ("margin-left" in body or "margin-right" in body):
                self.fail(f"card layout depends on a child margin again: {selector}")

    def test_the_stylesheet_url_carries_its_own_fingerprint(self):
        """A phone that already has the old CSS must not keep it after a fix."""
        token = bs.style_token()
        self.assertRegex(token, r"^[0-9a-f]{10}$")
        for name in ("index.html", "skills/cordon.html", "maintainers/index.html"):
            self.assertIn(f"style.css?v={token}", self.files[name])
        # The fingerprint has to follow the content, or it is decoration.
        original = bs.STYLE
        try:
            bs.STYLE = original + "\n/* changed */"
            self.assertNotEqual(bs.style_token(), token)
        finally:
            bs.STYLE = original

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
