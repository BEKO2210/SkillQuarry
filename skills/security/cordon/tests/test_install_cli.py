from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from harness import RepoFixture

SKILL = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_install_reinstall_and_uninstall_are_symmetric(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td) / "prefix with ' quote"
            env = os.environ.copy(); env["CORDON_PREFIX"] = str(prefix); env.pop("PYTHONPATH", None)
            first = subprocess.run([str(SKILL / "install.sh")], text=True, capture_output=True, env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            launcher = prefix / "bin/cordon"
            self.assertTrue(launcher.is_file())
            self.assertEqual(subprocess.run([str(launcher), "--version"], text=True, capture_output=True).stdout.strip(), "cordon 1.0.0")
            release_dirs = list((prefix / "share/cordon/releases").iterdir())
            self.assertEqual(len(release_dirs), 1)
            second = subprocess.run([str(SKILL / "install.sh")], text=True, capture_output=True, env=env)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(len(list((prefix / "share/cordon/releases").iterdir())), 1)
            removed = subprocess.run([str(SKILL / "uninstall.sh")], text=True, capture_output=True, env=env)
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertFalse(launcher.exists()); self.assertFalse((prefix / "share/cordon").exists())

    def test_uninstall_does_not_touch_repository_state(self) -> None:
        fx = RepoFixture(); self.addCleanup(fx.close)
        state = fx.root / ".cordon"; state.mkdir(); (state / "sentinel").write_text("keep")
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td) / "prefix"
            env = os.environ.copy(); env["CORDON_PREFIX"] = str(prefix); env.pop("PYTHONPATH", None)
            subprocess.run([str(SKILL / "install.sh")], check=True, env=env, capture_output=True)
            subprocess.run([str(SKILL / "uninstall.sh")], check=True, env=env, capture_output=True)
        self.assertEqual((state / "sentinel").read_text(), "keep")


class CliTests(unittest.TestCase):
    def test_manual_cli_exit_codes_and_json(self) -> None:
        fx = RepoFixture(); self.addCleanup(fx.close)
        env = os.environ.copy(); env["PYTHONPATH"] = str(SKILL / "src")
        arm = subprocess.run([
            "python3", "-m", "cordon", "--repo", str(fx.root), "arm", "small change",
            "--allow", "src/**", "--max-files", "1", "--max-added-lines", "2"
        ], text=True, capture_output=True, env=env)
        self.assertEqual(arm.returncode, 0, arm.stderr)
        self.assertEqual(json.loads(arm.stdout)["phase"], "armed")
        (fx.root / "src/new.py").write_text("one\ntwo\nthree\n")
        check = subprocess.run(["python3", "-m", "cordon", "--repo", str(fx.root), "check"], text=True, capture_output=True, env=env)
        self.assertEqual(check.returncode, 3)
        self.assertFalse(json.loads(check.stdout)["passed"])
        reset = subprocess.run(["python3", "-m", "cordon", "--repo", str(fx.root), "reset"], text=True, capture_output=True, env=env)
        self.assertEqual(reset.returncode, 0); self.assertFalse((fx.root / ".cordon").exists())
