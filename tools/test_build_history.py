#!/usr/bin/env python3
"""Tests for the git-derived version history.

    python3 tools/test_build_history.py
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_history as bh


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(bh.render())

    def test_every_registry_skill_has_history(self):
        registry = {str(item["name"]) for item in bh.load_registry()}
        self.assertEqual(set(self.document["skills"]), registry)

    def test_versions_are_newest_first(self):
        for name, entry in self.document["skills"].items():
            dates = [item["date"] for item in entry["versions"]]
            with self.subTest(skill=name):
                self.assertEqual(dates, sorted(dates, reverse=True))

    def test_each_version_carries_a_number_and_a_date(self):
        for entry in self.document["skills"].values():
            for item in entry["versions"]:
                self.assertRegex(item["version"], r"^\d+\.\d+\.\d+")
                self.assertRegex(item["date"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                                 "dates must have one spelling, independent of the git version")

    def test_the_history_only_moves_when_a_version_moves(self):
        """It is committed, so it must not change on every unrelated commit."""
        first = bh.render()
        self.assertEqual(first, bh.render())
        self.assertNotIn('"commits"', first)

    def test_the_version_timeline_matches_the_manifests(self):
        for skill in bh.load_registry():
            entry = self.document["skills"][str(skill["name"])]
            with self.subTest(skill=skill["name"]):
                self.assertTrue(entry["versions"])
                self.assertEqual(entry["versions"][0]["version"], skill["version"])

    def test_released_is_the_newest_version_date(self):
        for entry in self.document["skills"].values():
            if entry["versions"]:
                self.assertEqual(entry["released"], entry["versions"][0]["date"])

    def test_the_committed_file_is_current(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = bh.main(["--check"])
        self.assertEqual(code, 0, err.getvalue())

    def test_drift_is_reported(self):
        with mock.patch.object(bh, "render", return_value="{}\n"):
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                code = bh.main(["--check"])
        self.assertEqual(code, bh.EXIT_STALE)
        self.assertIn("out of date", err.getvalue())

    def test_a_shallow_clone_is_refused(self):
        with mock.patch.object(bh, "git", return_value="true\n"):
            with self.assertRaisesRegex(bh.HistoryError, "shallow"):
                bh.ensure_full_history()

    def test_timestamps_are_normalised_to_utc_z(self):
        self.assertEqual(bh.utc_iso("0"), "1970-01-01T00:00:00Z")
        self.assertEqual(bh.utc_iso("1770000000"), "2026-02-02T02:40:00Z")

    def test_a_failing_git_call_is_reported(self):
        with self.assertRaises(bh.HistoryError):
            bh.git("rev-parse", "--verify", "refs/heads/definitely-not-a-branch")

    def test_a_commit_without_a_manifest_yields_no_version(self):
        self.assertIsNone(bh.version_at("HEAD", "skills/none/ghost"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
