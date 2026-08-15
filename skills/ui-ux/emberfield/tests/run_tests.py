#!/usr/bin/env python3
"""Emberfield's tests.

A creative skill still makes checkable promises. The structural suite pins the
contract — the viewer's control IDs, the seeding law, the licence and notice
that let this derivative exist. The rendering suite holds the promise that
matters most: the same seed produces the same pixels, twice, in a real
headless Chromium — and a different seed does not.

Suites that need a browser or the network skip cleanly where those are missing
and fail instead when EMBERFIELD_REQUIRE=1, so CI cannot go green by skipping.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "templates" / "viewer.html"
GENERATOR = ROOT / "templates" / "generator.js"

STRICT = os.environ.get("EMBERFIELD_REQUIRE") == "1"

# The artwork loads this exact file; the tests render with the same bytes.
P5_URL = "https://cdnjs.cloudflare.com/ajax/libs/p5.js/1.7.0/p5.min.js"
P5_SHA256 = "bb7f8f14b9ce2e2344ff5cd6c06f2e105eb99541ecbfec77139e2886d9c0b9ba"

CONTROL_IDS = (
    "seed-input", "regenerate", "seed-prev", "seed-next", "seed-random",
    "save-png", "canvas-container",
)


def browser() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def require(condition: bool, reason: str) -> None:
    if condition:
        return
    if STRICT:
        raise AssertionError(f"EMBERFIELD_REQUIRE=1 but {reason}")
    raise unittest.SkipTest(reason)


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.viewer = VIEWER.read_text("utf-8")

    def test_every_control_the_frame_promises_exists(self):
        for control in CONTROL_IDS:
            self.assertIn(f'id="{control}"', self.viewer, f"missing #{control}")

    def test_the_seeding_law_is_in_the_template(self):
        """The demo must model the law the skill demands of every artwork."""
        self.assertIn("randomSeed(frame.seed())", self.viewer)
        self.assertIn("noiseSeed(frame.seed())", self.viewer)

    def test_unseeded_randomness_appears_only_on_the_random_button(self):
        uses = [line for line in self.viewer.splitlines() if "Math.random" in line]
        self.assertEqual(len(uses), 1, uses)
        self.assertIn("seed-random", uses[0])

    def test_no_clock_flows_into_the_drawing(self):
        for forbidden in ("Date.now", "performance.now", "new Date"):
            self.assertNotIn(forbidden, self.viewer)

    def test_the_cdn_script_is_pinned_with_integrity(self):
        self.assertIn(P5_URL, self.viewer)
        self.assertIn('integrity="sha384-', self.viewer)
        self.assertIn('crossorigin="anonymous"', self.viewer)

    def test_the_viewer_carries_no_upstream_branding(self):
        """The licence covers the code, not the trademarks."""
        self.assertNotIn("anthropic", self.viewer.lower())

    def test_the_viewer_is_self_contained_but_for_p5(self):
        externals = re.findall(r'(?:src|href)="(https?://[^"]+)"', self.viewer)
        self.assertEqual([url for url in externals if not url.startswith("https://p5js.org")],
                         [P5_URL])


class ProvenanceTests(unittest.TestCase):
    def test_the_upstream_licence_ships_unchanged(self):
        text = (ROOT / "LICENSE.txt").read_text("utf-8")
        self.assertIn("Apache License", text)
        self.assertIn("Version 2.0", text)

    def test_the_notice_states_origin_and_changes(self):
        notice = (ROOT / "NOTICE.md").read_text("utf-8")
        for needed in ("algorithmic-art", "anthropics/skills", "Apache License 2.0",
                       "What was changed"):
            self.assertIn(needed, notice)

    def test_the_generator_template_keeps_its_guidance(self):
        text = GENERATOR.read_text("utf-8")
        self.assertIn("SEEDED RANDOMNESS", text)
        self.assertIn("PARAMETER ORGANIZATION", text)

    def test_the_skill_document_teaches_the_two_steps(self):
        skill = (ROOT / "SKILL.md").read_text("utf-8")
        for needed in ("algorithmic philosophy", "randomSeed(frame.seed())",
                       "same seed", "NOTICE.md"):
            self.assertIn(needed, skill)


class GeneratorSyntaxTests(unittest.TestCase):
    def test_the_generator_template_parses_as_javascript(self):
        node = shutil.which("node")
        require(node is not None, "node is not installed")
        finished = subprocess.run([node, "--check", str(GENERATOR)],
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(finished.returncode, 0, finished.stderr[-500:])


class RenderingTests(unittest.TestCase):
    """The promise itself: seeds are destiny."""

    chrome: str
    workdir: Path

    @classmethod
    def setUpClass(cls) -> None:
        found = browser()
        require(found is not None, "no Chromium-family browser found")
        cls.chrome = str(found)
        cls.temp = tempfile.TemporaryDirectory(prefix="emberfield-")
        cls.workdir = Path(cls.temp.name)

        cache = ROOT / "tests" / ".cache"
        cache.mkdir(exist_ok=True)
        p5 = cache / "p5.min.js"
        if not p5.is_file():
            try:
                with urllib.request.urlopen(P5_URL, timeout=60) as response:
                    p5.write_bytes(response.read())
            except OSError:
                require(False, "p5.js is not cached and the network is unreachable")
        digest = hashlib.sha256(p5.read_bytes()).hexdigest()
        if digest != P5_SHA256:
            p5.unlink()
            raise AssertionError(f"pinned p5.js hash mismatch: {digest}")

        # The rendered page uses the same bytes the CDN serves, from disk, so
        # this suite neither depends on the CDN nor drifts from it.
        source = VIEWER.read_text("utf-8")
        source = re.sub(r'<script src="https://cdnjs[^>]+>', '<script src="p5.min.js">', source)
        (cls.workdir / "p5.min.js").write_bytes(p5.read_bytes())
        for name, seed in (("a.html", 12345), ("b.html", 12345), ("c.html", 512144)):
            (cls.workdir / name).write_text(
                source.replace('id="seed-input" value="12345"', f'id="seed-input" value="{seed}"'),
                "utf-8",
            )

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def render(self, page: str, shot: str) -> bytes:
        out = self.workdir / shot
        finished = subprocess.run(
            [self.chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
             "--window-size=1200,800", "--virtual-time-budget=8000", "--disable-lcd-text",
             f"--screenshot={out}", f"--user-data-dir={self.workdir}/profile-{shot}",
             (self.workdir / page).as_uri()],
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(finished.returncode, 0, finished.stderr[-500:])
        data = out.read_bytes()
        self.assertGreater(len(data), 10_000, "screenshot suspiciously small")
        return data

    def test_the_same_seed_renders_the_same_pixels(self):
        first = self.render("a.html", "a.png")
        second = self.render("b.html", "b.png")
        self.assertEqual(hashlib.sha256(first).hexdigest(),
                         hashlib.sha256(second).hexdigest(),
                         "seed 12345 rendered two different images")

    def test_a_different_seed_renders_a_different_image(self):
        """Guards the other side: if rendering failed silently, both runs would
        agree on an empty canvas and the determinism test would lie."""
        base = self.render("a.html", "a2.png")
        other = self.render("c.html", "c.png")
        self.assertNotEqual(hashlib.sha256(base).hexdigest(),
                            hashlib.sha256(other).hexdigest(),
                            "seeds 12345 and 512144 rendered identical images")


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"\nran {result.testsRun}, skipped {len(result.skipped)}, "
          f"failed {len(result.failures)}, errored {len(result.errors)}")
    if result.skipped and STRICT:
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
