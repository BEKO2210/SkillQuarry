#!/usr/bin/env python3
"""Tests for the reproducible skill packaging.

    python3 tools/test_package_skills.py
"""

from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import package_skills as ps


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.skills = ps.load_registry()
        self.archives = {str(s["name"]): ps.build_archive(s) for s in self.skills}

    def test_one_archive_per_skill_plus_checksums(self):
        files = ps.render()
        self.assertEqual(len(files), len(self.skills) + 1)
        self.assertIn("SHA256SUMS", files)

    def test_archives_are_byte_for_byte_reproducible(self):
        for skill in self.skills:
            with self.subTest(skill=skill["name"]):
                self.assertEqual(ps.build_archive(skill), self.archives[str(skill["name"])])

    def test_entries_are_sorted_and_time_independent(self):
        for name, data in self.archives.items():
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                members = archive.getmembers()
            with self.subTest(skill=name):
                self.assertEqual([m.name for m in members], sorted(m.name for m in members))
                self.assertTrue(all(m.mtime == ps.FIXED_MTIME for m in members))
                self.assertTrue(all(m.uid == 0 and m.gid == 0 for m in members))

    def test_every_archive_unpacks_into_one_versioned_directory(self):
        for skill in self.skills:
            data = self.archives[str(skill["name"])]
            root = f"{skill['name']}-{skill['version']}"
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                names = archive.getnames()
            with self.subTest(skill=skill["name"]):
                self.assertTrue(all(name.startswith(f"{root}/") for name in names), names[:3])

    def test_the_installer_keeps_its_executable_bit(self):
        with tarfile.open(fileobj=io.BytesIO(self.archives["strata"]), mode="r:gz") as archive:
            installer = archive.getmember("strata-1.0.0/install.sh")
        self.assertEqual(installer.mode, 0o755)

    def test_build_output_and_caches_are_left_out(self):
        for name, data in self.archives.items():
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                names = archive.getnames()
            with self.subTest(skill=name):
                self.assertFalse([n for n in names if "__pycache__" in n or "/target/" in n])

    def test_checksums_describe_the_archives(self):
        files = ps.render()
        recorded = dict(
            (line.split("  ")[1], line.split("  ")[0])
            for line in files["SHA256SUMS"].decode("utf-8").splitlines()
        )
        for name, data in files.items():
            if name == "SHA256SUMS":
                continue
            with self.subTest(archive=name):
                self.assertEqual(recorded[name], hashlib.sha256(data).hexdigest())

    def test_a_skill_whose_directory_vanished_is_reported(self):
        with self.assertRaisesRegex(ps.PackageError, "does not exist"):
            ps.build_archive({"name": "ghost", "version": "1.0.0", "path": "skills/none/ghost"})


class CommandLineTests(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ps.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_writing_and_checking_a_fresh_dist(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ps, "DIST", Path(tmp) / "dist"):
                code, out, _ = self.run_main()
                self.assertEqual(code, 0)
                self.assertIn("wrote", out)
                code, out, _ = self.run_main("--check")
                self.assertEqual(code, 0)
                self.assertIn("matches the sources", out)

    def test_a_modified_archive_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "dist"
            with mock.patch.object(ps, "DIST", dist):
                self.run_main()
                (dist / "SHA256SUMS").write_text("tampered\n", encoding="utf-8")
                code, _, err = self.run_main("--check")
        self.assertEqual(code, ps.EXIT_STALE)
        self.assertIn("out of date", err)

    def test_an_unusable_registry_is_reported(self):
        with mock.patch.object(ps, "load_registry", side_effect=ps.PackageError("registry has no skills")):
            code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("registry has no skills", err)

    def test_a_missing_registry_file_is_reported(self):
        with mock.patch.object(ps, "REGISTRY", Path("/nonexistent/skills.json")):
            with self.assertRaisesRegex(ps.PackageError, "cannot read"):
                ps.load_registry()


if __name__ == "__main__":
    unittest.main(verbosity=2)
