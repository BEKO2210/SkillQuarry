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

    def test_commits_are_newest_first_and_bounded(self):
        for name, entry in self.document["skills"].items():
            dates = [commit["date"] for commit in entry["commits"]]
            with self.subTest(skill=name):
                self.assertEqual(dates, sorted(dates, reverse=True))
                self.assertLessEqual(len(dates), bh.MAX_COMMITS)

    def test_each_commit_carries_a_sha_date_and_subject(self):
        for entry in self.document["skills"].values():
            for commit in entry["commits"]:
                self.assertTrue(commit["sha"])
                self.assertRegex(commit["date"], r"^\d{4}-\d{2}-\d{2}T")
                self.assertTrue(commit["subject"])

    def test_the_version_timeline_matches_the_manifests(self):
        for skill in bh.load_registry():
            entry = self.document["skills"][str(skill["name"])]
            with self.subTest(skill=skill["name"]):
                self.assertTrue(entry["versions"])
                self.assertEqual(entry["versions"][0]["version"], skill["version"])

    def test_last_changed_is_the_newest_commit(self):
        for entry in self.document["skills"].values():
            if entry["commits"]:
                self.assertEqual(entry["last_changed"], entry["commits"][0]["date"])

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

    def test_a_failing_git_call_is_reported(self):
        with self.assertRaises(bh.HistoryError):
            bh.git("rev-parse", "--verify", "refs/heads/definitely-not-a-branch")

    def test_a_commit_without_a_manifest_yields_no_version(self):
        self.assertIsNone(bh.version_at("HEAD", "skills/none/ghost"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
