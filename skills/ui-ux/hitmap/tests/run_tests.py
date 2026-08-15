#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hitmap.core import classify_probe, sample_points, stable_finding_id, summarize
from hitmap.cdp import find_browser


def blocked(selector="#go", receiver="#overlay"):
    return {
        "selector": selector,
        "eligible": True,
        "samples": [{"reachable": False, "receiver": receiver} for _ in range(9)],
    }


class CoreTests(unittest.TestCase):
    def test_sample_points_exact_nine(self):
        pts = sample_points({"x": 0, "y": 0, "width": 100, "height": 50})
        self.assertEqual(len(pts), 9)
        self.assertEqual(pts[0], (50, 25))
        self.assertEqual(pts[-1], (20, 25))

    def test_sample_points_reject_zero_width(self):
        self.assertEqual(sample_points({"x": 0, "y": 0, "width": 0, "height": 5}), [])

    def test_sample_points_reject_zero_height(self):
        self.assertEqual(sample_points({"x": 0, "y": 0, "width": 5, "height": 0}), [])

    def test_stable_id(self):
        self.assertEqual(stable_finding_id(2, 'button[aria-label="Go now"]'), "HITMAP-0002-button-aria-label-go-now")

    def test_stable_id_fallback(self):
        self.assertEqual(stable_finding_id(1, '---'), "HITMAP-0001-target")

    def test_ineligible_not_reported(self):
        p = blocked()
        p["eligible"] = False
        self.assertIsNone(classify_probe(p, 1))

    def test_wrong_sample_count_not_reported(self):
        p = blocked()
        p["samples"] = p["samples"][:-1]
        self.assertIsNone(classify_probe(p, 1))

    def test_one_reachable_point_is_not_high_confidence(self):
        p = blocked()
        p["samples"][4]["reachable"] = True
        self.assertIsNone(classify_probe(p, 1))

    def test_blocked_target_reported(self):
        f = classify_probe(blocked(), 7)
        self.assertIsNotNone(f)
        self.assertEqual(f.sampled_points, 9)
        self.assertEqual(f.reachable_points, 0)
        self.assertEqual(f.occluders, ("#overlay",))
        self.assertEqual(f.confidence, "geometry")

    def test_occluders_are_deduplicated_and_sorted(self):
        p = blocked()
        p["samples"][0]["receiver"] = "z"
        p["samples"][1]["receiver"] = None
        f = classify_probe(p, 1)
        self.assertEqual(f.occluders, ("#overlay", "<none>", "z"))

    def test_missing_selector_is_stable(self):
        p = blocked()
        del p["selector"]
        f = classify_probe(p, 1)
        self.assertEqual(f.selector, "<unknown>")

    def test_summarize_pass(self):
        p = blocked()
        p["samples"][0]["reachable"] = True
        r = summarize([p])
        self.assertEqual(r, {"verdict": "PASS", "targets": 1, "findings": []})

    def test_summarize_fail_shape(self):
        r = summarize([blocked("#start", "#cover")])
        self.assertEqual(r["verdict"], "FAIL")
        self.assertEqual(r["targets"], 1)
        self.assertEqual(r["findings"][0]["selector"], "#start")
        self.assertEqual(r["findings"][0]["sampled_points"], 9)
        self.assertEqual(r["findings"][0]["confidence"], "geometry")

    def test_two_findings_have_distinct_ids(self):
        r = summarize([blocked("#a"), blocked("#a")])
        self.assertNotEqual(r["findings"][0]["id"], r["findings"][1]["id"])


class DoctorTests(unittest.TestCase):
    def test_explicit_missing_browser(self):
        self.assertIsNone(find_browser("definitely-not-a-browser-xyz"))

    def test_explicit_file_browser(self):
        with tempfile.NamedTemporaryFile() as f:
            self.assertEqual(find_browser(f.name), f.name)

    def test_env_missing_browser(self):
        old = os.environ.get("HITMAP_BROWSER")
        os.environ["HITMAP_BROWSER"] = "definitely-not-a-browser-xyz"
        try:
            self.assertIsNone(find_browser())
        finally:
            if old is None:
                os.environ.pop("HITMAP_BROWSER", None)
            else:
                os.environ["HITMAP_BROWSER"] = old


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min", type=float, default=0)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    print(f"\n{result.testsRun} tests passed")
    if args.min > result.testsRun:
        print(f"FAIL: expected at least {args.min:g} tests", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
