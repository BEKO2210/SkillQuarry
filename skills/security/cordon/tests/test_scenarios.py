from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

import cordon.core as c
from harness import create_non_utf8_file, RepoFixture, run


class FixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = RepoFixture()
        self.addCleanup(self.fx.close)
        self.policy = c.Policy(("src/**",), limits=c.Limits(10, 100, 100, 100_000, 1))


class BeginnerScenario(FixtureTest):
    def test_manual_arm_edit_check(self) -> None:
        c.arm_session(self.fx.root, label="Change app value", policy=self.policy)
        (self.fx.root / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        audit = c.check_session(self.fx.root)
        self.assertTrue(audit.passed)
        self.assertEqual(audit.changed_files, ("src/app.py",))
        self.assertEqual(c.session_status(self.fx.root)["phase"], "accepted")


class EverydayScenario(FixtureTest):
    def test_claude_multi_step_with_verifier(self) -> None:
        env = self.fx.sequence([
            {"write": {"src/app.py": "VALUE = 2\n", "src/new.py": "OK = True\n"}, "claim": "complete"}
        ])
        old = os.environ.copy()
        os.environ.update(env)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        process, audit = c.run_claude_session(
            self.fx.root,
            label="Update app and add helper",
            policy=self.policy,
            verify=["python3 -c \"import pathlib; assert 'VALUE = 2' in pathlib.Path('src/app.py').read_text()\""],
            claude=self.fx.claude_config(),
        )
        self.assertEqual(process.returncode, 0)
        self.assertTrue(audit.passed)
        log = json.loads((self.fx.root / "fake-sequence.log").read_text().splitlines()[0])
        self.assertIn("--permission-mode", log["argv"])
        self.assertIn("acceptEdits", log["argv"])
        self.assertIn("independently inspect", log["prompt"])


class AdvancedScenario(FixtureTest):
    def test_crash_then_resume_from_partial_change(self) -> None:
        env = self.fx.sequence([
            {"write": {"src/app.py": "VALUE = 2\n"}, "stderr": "engine crashed", "exit": 7},
            {"write": {"src/app.py": "VALUE = 3\n"}, "claim": "fixed"},
        ])
        old = os.environ.copy(); os.environ.update(env)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        process1, audit1 = c.run_claude_session(
            self.fx.root, label="Set value to 3", policy=self.policy,
            verify=["python3 -c \"import pathlib; assert 'VALUE = 3' in pathlib.Path('src/app.py').read_text()\""],
            claude=self.fx.claude_config(),
        )
        self.assertEqual(process1.returncode, 7)
        self.assertFalse(audit1.passed)
        process2, audit2 = c.resume_claude_session(self.fx.root)
        self.assertEqual(process2.returncode, 0)
        self.assertTrue(audit2.passed)
        logs = [json.loads(line) for line in (self.fx.root / "fake-sequence.log").read_text().splitlines()]
        self.assertIn("Previous attempt ended", logs[1]["prompt"])


class ExpertScenario(FixtureTest):
    def test_agent_claims_success_verifier_vetoes_then_resume_repairs(self) -> None:
        env = self.fx.sequence([
            {"write": {"src/app.py": "VALUE = 9\n"}, "claim": "SUCCESS"},
            {"write": {"src/app.py": "VALUE = 10\n"}, "claim": "SUCCESS"},
        ])
        old = os.environ.copy(); os.environ.update(env)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        _process, first = c.run_claude_session(
            self.fx.root, label="Set value to ten", policy=self.policy,
            verify=["python3 -c \"import pathlib; assert 'VALUE = 10' in pathlib.Path('src/app.py').read_text()\""],
            claude=self.fx.claude_config(),
        )
        self.assertFalse(first.passed)
        self.assertTrue(any("verifier failed" in item for item in first.violations))
        _process, second = c.resume_claude_session(self.fx.root)
        self.assertTrue(second.passed)
        log2 = json.loads((self.fx.root / "fake-sequence.log").read_text().splitlines()[1])
        self.assertIn("Verifier", log2["prompt"])


class AdversarialScenario(FixtureTest):
    def test_corrupt_state_scope_break_attempt_ceiling_and_pathological_name(self) -> None:
        c.arm_session(self.fx.root, label="Scoped edit", policy=self.policy, max_attempts=1, mode="claude", claude=self.fx.claude_config())
        weird = self.fx.root / "src" / "line\nbreak\tname.py"
        weird.write_text("x=1\n", encoding="utf-8")
        audit = c.check_session(self.fx.root)
        self.assertTrue(audit.passed)
        self.assertIn("src/line\nbreak\tname.py", audit.changed_files)
        c.reset_session(self.fx.root)
        weird.unlink()

        c.arm_session(self.fx.root, label="Scoped edit", policy=self.policy)
        (self.fx.root / "README.md").write_text("outside\n", encoding="utf-8")
        bad = c.check_session(self.fx.root)
        self.assertFalse(bad.passed)
        self.assertTrue(any("outside policy" in item for item in bad.violations))
        c.reset_session(self.fx.root)

        run("git", "checkout", "--", "README.md", cwd=self.fx.root)
        c.arm_session(self.fx.root, label="Corruption", policy=self.policy)
        (self.fx.root / ".cordon" / "state.json").write_text("not json", encoding="utf-8")
        with self.assertRaises(c.StateError):
            c.session_status(self.fx.root)

class AdversarialByteFilenameScenario(FixtureTest):
    def test_non_utf8_git_filename_survives_audit_and_json(self) -> None:
        baseline = c.current_head(self.fx.root)
        if create_non_utf8_file(self.fx.root / "src", b"invalid-\xff.py", b"x = 1\n") is None:
            # APFS refuses non-UTF-8 names outright; the decoding path is still covered.
            self.assertEqual(c._display_path(b"src/invalid-\xff.py"), "src/invalid-\udcff.py")
            self.assertIn(b"\\udc", c.canonical_json({"p": c._display_path(b"x-\xff")}))
            self.skipTest("filesystem rejects non-UTF-8 filenames")
        audit = c.audit_policy(
            self.fx.root,
            baseline,
            c.Policy(("src/**",), limits=c.Limits(5, 20, 20, 1000, 1)),
        )
        self.assertTrue(audit.passed, audit.violations)
        payload = c.canonical_json(audit.as_dict())
        self.assertIn(b"\\udc", payload)
