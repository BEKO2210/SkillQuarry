from __future__ import annotations

import errno
import io
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import cordon.core as c
from harness import RepoFixture, create_non_utf8_file, run


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = RepoFixture()
        self.addCleanup(self.fx.close)
        self.policy = c.Policy(("src/**",), limits=c.Limits(10, 100, 100, 100_000, 1))


class ValidationTests(unittest.TestCase):
    def test_limits_reject_negative_and_bool(self) -> None:
        for limits in (c.Limits(max_files=-1), c.Limits(max_files=True)):
            with self.subTest(limits=limits), self.assertRaises(c.PolicyError):
                limits.validate()

    def test_policy_requires_allow_and_caps_pattern_count(self) -> None:
        with self.assertRaises(c.PolicyError):
            c.Policy(()).validate()
        with self.assertRaises(c.PolicyError):
            c.Policy(tuple("x" for _ in range(c.MAX_PATTERNS + 1))).validate()

    def test_pattern_validation_matrix(self) -> None:
        bad = ["", None, "x" * (c.MAX_PATTERN_LENGTH + 1), "a\x00b", "/src/**", "./src/**", "src/../x", "src/./x"]
        for pattern in bad:
            with self.subTest(pattern=pattern), self.assertRaises(c.PolicyError):
                c.validate_pattern(pattern)  # type: ignore[arg-type]

    def test_glob_semantics_and_deny_wins(self) -> None:
        policy = c.Policy(("**/test?.py", "src/*"), ("src/private*",))
        self.assertTrue(c.path_allowed("pkg/test1.py", policy))
        self.assertTrue(c.path_allowed("test2.py", policy))
        self.assertTrue(c.path_allowed("src/a", policy))
        self.assertFalse(c.path_allowed("src/deep/a", policy))
        self.assertFalse(c.path_allowed("src/private1", policy))

    def test_policy_from_dict_rejects_every_schema_shape(self) -> None:
        good = c.policy_to_dict(c.Policy(("src/**",)))
        bad_values = [
            None,
            {"allow": [], "deny": [], "limits": {}, "allow_commits": False, "extra": 1},
            {**good, "allow": "src/**"},
            {**good, "deny": [1]},
            {**good, "limits": []},
            {**good, "limits": {"max_files": 1}},
            {**good, "allow_commits": "no"},
            {**good, "allow": []},
        ]
        for value in bad_values:
            with self.subTest(value=value), self.assertRaises(c.StateError):
                c.policy_from_dict(value)
        self.assertEqual(c.policy_from_dict(good).allow, ("src/**",))


class AtomicWriteTests(unittest.TestCase):
    def test_hash_missing_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as td, self.assertRaises(c.StateError):
            c.sha256_file(Path(td) / "missing")

    def test_directory_fsync_tolerates_known_unsupported_errors_and_raises_other(self) -> None:
        for code in (errno.EINVAL, errno.ENOTSUP, errno.EACCES):
            with self.subTest(code=code), mock.patch.object(c.os, "open", side_effect=OSError(code, "x")):
                c._fsync_directory(Path("."))
        with mock.patch.object(c.os, "open", side_effect=OSError(errno.EIO, "x")), self.assertRaises(OSError):
            c._fsync_directory(Path("."))

    def test_atomic_write_cleans_temp_on_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state"
            with mock.patch.object(c.os, "replace", side_effect=OSError("boom")), self.assertRaises(OSError):
                c.atomic_write_bytes(path, b"data")
            self.assertEqual([p for p in Path(td).iterdir() if p.name.startswith(".state.")], [])

    def test_atomic_text_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            text = Path(td) / "x.txt"
            obj = Path(td) / "x.json"
            c.atomic_write_text(text, "hello", mode=0o640)
            c.atomic_write_json(obj, {"b": 2, "a": 1})
            self.assertEqual(text.read_text(), "hello")
            self.assertEqual(obj.read_bytes(), b'{"a":1,"b":2}\n')


class ProcessTests(unittest.TestCase):
    def test_reader_thread_caps_and_closes(self) -> None:
        stream = io.BytesIO(b"abcdef")
        buf = bytearray(); event = threading.Event()
        c._reader_thread(stream, buf, 3, event)
        self.assertEqual(buf, b"abcd")
        self.assertTrue(event.is_set())
        self.assertTrue(stream.closed)
        stream2 = io.BytesIO(b"")
        c._reader_thread(stream2, bytearray(), 3, threading.Event())
        self.assertTrue(stream2.closed)

    def test_process_invalid_cap_and_missing_binary(self) -> None:
        for cap in (0, True, 1.5):
            with self.subTest(cap=cap), self.assertRaises(c.ProcessError):
                c.run_bounded_process(["true"], cwd=Path.cwd(), timeout=1, output_cap=cap)  # type: ignore[arg-type]
        for timeout in (0, -1, True, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(c.ProcessError):
                c.run_bounded_process(["true"], cwd=Path.cwd(), timeout=timeout)
        with self.assertRaises(c.ProcessError):
            c.run_bounded_process(["/definitely/not/a/binary"], cwd=Path.cwd(), timeout=1)

    def test_process_captures_both_streams(self) -> None:
        result = c.run_bounded_process(
            ["python3", "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
            cwd=Path.cwd(), timeout=2, output_cap=100,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"out", result.stdout); self.assertIn(b"err", result.stderr)

    def test_process_timeout(self) -> None:
        result = c.run_bounded_process(["python3", "-c", "import time; time.sleep(3)"], cwd=Path.cwd(), timeout=0.05)
        self.assertTrue(result.timed_out)
        self.assertNotEqual(result.returncode, 0)

    def test_process_output_cap(self) -> None:
        result = c.run_bounded_process(["python3", "-c", "import sys,time; sys.stdout.write('x'*10000); sys.stdout.flush(); time.sleep(1)"], cwd=Path.cwd(), timeout=2, output_cap=32)
        self.assertTrue(result.output_limited)
        self.assertLessEqual(len(result.stdout), 32)

    def test_terminate_already_exited_and_forced_kill_path(self) -> None:
        done = subprocess.Popen(["true"], start_new_session=True)
        done.wait()
        c._terminate_process_group(done)
        sleeper = subprocess.Popen(["python3", "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(5)"], start_new_session=True)
        time.sleep(0.08)
        c._terminate_process_group(sleeper, grace_seconds=0.01)
        self.assertIsNotNone(sleeper.poll())

    def test_reader_stuck_is_named(self) -> None:
        class Pipe:
            def close(self): pass
        class Proc:
            stdout = Pipe(); stderr = Pipe(); returncode = 0; pid = 999999
            def poll(self): return 0
        class Thread:
            def __init__(self, *a, **k): pass
            def start(self): pass
            def join(self, timeout=None): pass
            def is_alive(self): return True
        with mock.patch.object(c.subprocess, "Popen", return_value=Proc()), mock.patch.object(c.threading, "Thread", Thread), mock.patch.object(c, "_terminate_process_group") as term:
            with self.assertRaises(c.ProcessError):
                c.run_bounded_process(["fake"], cwd=Path.cwd(), timeout=1)
            term.assert_called_once()


class GitWrapperTests(Base):
    def test_git_error_modes(self) -> None:
        cases = [
            c.ProcessResult(("git",), 0, b"", b"", output_limited=True),
            c.ProcessResult(("git",), 0, b"", b"", timed_out=True),
            c.ProcessResult(("git",), 9, b"", b"bad"),
        ]
        for result in cases:
            with self.subTest(result=result), mock.patch.object(c, "run_bounded_process", return_value=result), self.assertRaises(c.RepositoryError):
                c._git(self.fx.root, ["status"])

    def test_repository_root_from_subdir_and_absolute_git_path_branch(self) -> None:
        self.assertEqual(c.repository_root(self.fx.root / "src"), self.fx.root.resolve())
        with mock.patch.object(c, "_git", return_value=os.fsencode(self.fx.root / ".git" / "info" / "exclude") + b"\n"):
            self.assertEqual(c._exclude_path(self.fx.root), (self.fx.root / ".git/info/exclude").resolve())

    def test_exclude_binary_safe_existing_marker_and_tamper(self) -> None:
        exclude = self.fx.root / ".git/info/exclude"
        exclude.write_bytes(exclude.read_bytes() + b"\xffcustom\n")
        first = c.ensure_local_exclude(self.fx.root)
        second = c.ensure_local_exclude(self.fx.root)
        self.assertEqual(first, second)
        c.atomic_write_bytes(exclude, exclude.read_bytes() + b"tamper\n")
        with self.assertRaises(c.StateError):
            c.verify_local_exclude(self.fx.root, first)

    def test_parse_numstat_matrix(self) -> None:
        self.assertEqual(c._parse_numstat(b"1\t2\ta\x00-\t-\tb.bin\x00"), {b"a": (1, 2), b"b.bin": (None, None)})
        for raw in (b"bad\x00", b"1\t2\t\x00", b"x\t2\ta\x00"):
            with self.subTest(raw=raw), self.assertRaises(c.RepositoryError):
                c._parse_numstat(raw)


class StateTests(Base):
    def _armed(self) -> tuple[dict, dict]:
        return c.arm_session(self.fx.root, label="x", policy=self.policy)

    def test_load_missing_and_non_object(self) -> None:
        with self.assertRaises(c.StateError):
            c._load_json_object(self.fx.root / "missing", "x")
        p = self.fx.root / "bad"; p.write_text("[]")
        with self.assertRaises(c.StateError): c._load_json_object(p, "x")
        p.write_text("{")
        with self.assertRaises(c.StateError): c._load_json_object(p, "x")

    def test_load_session_schema_and_integrity_matrix(self) -> None:
        config, state = self._armed()
        cfg_path = self.fx.root / ".cordon/config.json"; state_path = self.fx.root / ".cordon/state.json"
        variants = []
        variants.append(({**config, "schema_version": 99}, state))
        variants.append((config, {**state, "schema_version": 99}))
        variants.append((config, {**state, "attempt": True}))
        variants.append((config, {**state, "max_attempts": 0}))
        variants.append((config, {**state, "phase": 1}))
        variants.append((config, {**state, "attempt": state["max_attempts"] + 1}))
        variants.append((config, {**state, "last_error": 7}))
        variants.append((config, {**state, "updated_at": ""}))
        variants.append(({**config, "baseline": "bad"}, state))
        variants.append(({**config, "mode": "bad"}, state))
        variants.append(({**config, "label": ""}, state))
        variants.append(({**config, "verify": "true"}, state))
        variants.append(({**config, "verify": ["x" * (c.MAX_VERIFIER_LENGTH + 1)]}, state))
        variants.append(({**config, "claude": []}, state))
        variants.append(({**config, "claude": {**config["claude"], "timeout_seconds": float("nan")}}, state))
        variants.append(({**config, "created_at": ""}, state))
        for changed_config, changed_state in variants:
            with self.subTest(keys=(changed_config.get("mode"), changed_state.get("phase"))):
                changed_state = dict(changed_state)
                changed_state["config_sha256"] = c._config_hash(changed_config)
                c.atomic_write_json(cfg_path, changed_config); c.atomic_write_json(state_path, changed_state)
                with self.assertRaises(c.StateError): c.load_session(self.fx.root)
        c.atomic_write_json(cfg_path, {**config, "label": "tampered"})
        c.atomic_write_json(state_path, state)
        with self.assertRaises(c.StateError): c.load_session(self.fx.root)
        c.atomic_write_json(cfg_path, config); c.atomic_write_json(state_path, state)
        self.assertEqual(c.load_session(self.fx.root)[0]["label"], "x")

    def test_lock_conflict(self) -> None:
        self._armed()
        with c.repository_lock(self.fx.root):
            with self.assertRaises(c.LockError):
                with c.repository_lock(self.fx.root):
                    pass

    def test_audit_deserialize_errors(self) -> None:
        self.assertIsNone(c._audit_from_dict(None))
        with self.assertRaises(c.StateError): c._audit_from_dict([])
        with self.assertRaises(c.StateError): c._audit_from_dict({"passed": True})


class MeasurementTests(Base):
    def test_untracked_missing_symlink_dir_binary_no_newline_and_read_error(self) -> None:
        missing = c._measure_untracked(self.fx.root, b"missing")
        self.assertIn("disappeared", missing[3] or "")
        link = self.fx.root / "link"; link.symlink_to("target")
        self.assertEqual(c._measure_untracked(self.fx.root, b"link")[:3], (6, 1, False))
        folder = self.fx.root / "folder"; folder.mkdir()
        self.assertIn("not a regular", c._measure_untracked(self.fx.root, b"folder")[3] or "")
        binary = self.fx.root / "bin"; binary.write_bytes(b"a\x00b")
        self.assertTrue(c._measure_untracked(self.fx.root, b"bin")[2])
        text = self.fx.root / "text"; text.write_bytes(b"a\nb")
        self.assertEqual(c._measure_untracked(self.fx.root, b"text")[1], 2)
        with mock.patch("builtins.open", side_effect=OSError("no")):
            self.assertIn("cannot read", c._measure_untracked(self.fx.root, b"text")[3] or "")

    def test_streaming_scan_cap_handles_growth_after_preflight(self) -> None:
        path = self.fx.root / "src/growing.txt"
        path.write_bytes(b"x")
        with self.assertRaises(c.PolicyError):
            c._measure_untracked(self.fx.root, b"src/growing.txt", scan_budget=-1)
        fake_stream = io.BytesIO(b"x" * 65)
        with mock.patch("builtins.open", return_value=fake_stream):
            measured = c._measure_untracked(
                self.fx.root, b"src/growing.txt", scan_budget=64
            )
        self.assertEqual(measured[4], 65)
        self.assertIn("scan safety cap exceeded during read", measured[3] or "")
        self.assertGreaterEqual(measured[0], 65)

        baseline = c.current_head(self.fx.root)
        with mock.patch.object(c, "MAX_UNTRACKED_SCAN_BYTES", 64), \
             mock.patch("builtins.open", side_effect=lambda *args, **kwargs: io.BytesIO(b"x" * 65)):
            audit = c.audit_policy(
                self.fx.root, baseline, c.Policy(("src/**",), limits=c.Limits(2, 100, 100, 1000, 2))
            )
        self.assertTrue(any("scan safety cap exceeded during read" in item for item in audit.violations))

    def test_budget_worst_cases_exact_boundary_and_one_over(self) -> None:
        policy = c.Policy(("src/**",), limits=c.Limits(1, 1, 0, 4, 0))
        baseline = c.current_head(self.fx.root)
        p = self.fx.root / "src/new.py"; p.write_bytes(b"x=1\n")
        exact = c.audit_policy(self.fx.root, baseline, policy)
        self.assertTrue(exact.passed)
        p.write_bytes(b"x=1\ny=2\n")
        over = c.audit_policy(self.fx.root, baseline, policy)
        self.assertFalse(over.passed)
        self.assertTrue(any("added-line budget" in x or "working-byte budget" in x for x in over.violations))

    def test_all_budgets_binary_commit_and_allow_commit(self) -> None:
        baseline = c.current_head(self.fx.root)
        (self.fx.root / "src/app.py").write_text("A\nB\nC\n")
        (self.fx.root / "src/a.bin").write_bytes(b"\x00")
        (self.fx.root / "src/b.py").write_text("one\ntwo\n")
        tiny = c.Policy(("src/**",), limits=c.Limits(1, 0, 0, 0, 0))
        audit = c.audit_policy(self.fx.root, baseline, tiny)
        joined = "\n".join(audit.violations)
        self.assertIn("file budget", joined); self.assertIn("added-line budget", joined); self.assertIn("deleted-line budget", joined)
        self.assertIn("working-byte budget", joined); self.assertIn("binary-file budget", joined)
        run("git", "add", "src/app.py", cwd=self.fx.root); run("git", "commit", "-q", "-m", "agent commit", cwd=self.fx.root)
        blocked = c.audit_policy(self.fx.root, baseline, c.Policy(("src/**",), allow_commits=False))
        self.assertTrue(any("HEAD changed" in x for x in blocked.violations))
        allowed = c.audit_policy(self.fx.root, baseline, c.Policy(("src/**",), allow_commits=True))
        self.assertFalse(any("HEAD changed" in x for x in allowed.violations))

    def test_scan_cap_is_mathematical_not_random(self) -> None:
        baseline = c.current_head(self.fx.root)
        with mock.patch.object(c, "MAX_UNTRACKED_SCAN_BYTES", 64):
            p = self.fx.root / "src/cap.bin"; p.write_bytes(b"x" * 64)
            at_cap = c.audit_policy(self.fx.root, baseline, c.Policy(("src/**",), limits=c.Limits(2, 100, 100, 1000, 2)))
            self.assertFalse(any("scan safety cap" in x for x in at_cap.violations))
            p.write_bytes(b"x" * 65)
            over = c.audit_policy(self.fx.root, baseline, c.Policy(("src/**",), limits=c.Limits(2, 100, 100, 1000, 2)))
            self.assertTrue(any("scan safety cap exceeded: 65 > 64" in x for x in over.violations))

    def test_lstat_race_and_special_tracked_type_are_rejected(self) -> None:
        baseline = c.current_head(self.fx.root)
        (self.fx.root / "src/app.py").write_text("changed\n")
        real = c.os.lstat
        def fail_once(path):
            if str(path).endswith("src/app.py"): raise OSError("race")
            return real(path)
        with mock.patch.object(c.os, "lstat", side_effect=fail_once):
            audit = c.audit_policy(self.fx.root, baseline, self.policy)
        self.assertTrue(any("cannot stat" in x for x in audit.violations))
        with mock.patch.object(c.os, "lstat", return_value=mock.Mock(st_mode=stat_mode_dir(), st_size=0)):
            audit2 = c.audit_policy(self.fx.root, baseline, self.policy)
        self.assertTrue(any("unsupported file type" in x for x in audit2.violations))


def stat_mode_dir() -> int:
    import stat
    return stat.S_IFDIR | 0o755


class VerifierTests(Base):
    def test_verifier_parse_errors(self) -> None:
        for commands in (["'"], ["   "], ["''"], "echo ok", ["x" * (c.MAX_VERIFIER_LENGTH + 1)], ["true"] * (c.MAX_VERIFIERS + 1)):
            with self.subTest(commands_type=type(commands).__name__, size=len(commands)), self.assertRaises(c.PolicyError):
                c.run_verifiers(self.fx.root, commands, timeout=1, output_cap=100)  # type: ignore[arg-type]

    def test_verifier_timeout_output_limit_and_policy_short_circuit(self) -> None:
        baseline = c.current_head(self.fx.root)
        timeout = c.audit_with_verification(self.fx.root, baseline, self.policy, ["python3 -c 'import time; time.sleep(2)'"], verify_timeout=0.03)
        self.assertTrue(any("timeout" in x for x in timeout.violations))
        limited = c.audit_with_verification(self.fx.root, baseline, self.policy, ["python3 -c \"print('x'*1000)\""], output_cap=8)
        self.assertTrue(any("output limit" in x for x in limited.violations))
        stored = c.run_verifiers(
            self.fx.root,
            ["python3 -c \"print('x'*20000)\""],
            timeout=2,
            output_cap=30000,
        )[0]
        self.assertTrue(stored.passed)
        self.assertIn("...[truncated by Cordon]", stored.stdout)
        self.assertLessEqual(len(stored.stdout), c.MAX_STORED_VERIFIER_BYTES + 32)
        self.assertEqual(c._stored_verifier_text(b"ok"), "ok")
        (self.fx.root / "README.md").write_text("bad\n")
        with mock.patch.object(c, "run_verifiers") as verifier:
            blocked = c.audit_with_verification(self.fx.root, baseline, self.policy, ["false"])
        self.assertFalse(blocked.passed); verifier.assert_not_called()


class ClaudeConfigAndArmTests(Base):
    def test_build_args_minimal(self) -> None:
        config = {"claude": {"binary": "claude", "max_turns": 1, "max_budget_usd": None, "model": None, "effort": None}}
        args = c.build_claude_args(config, "p")
        self.assertNotIn("--model", args); self.assertNotIn("--effort", args); self.assertNotIn("--max-budget-usd", args)

    def test_prompt_matches_budgets_and_commit_policy(self) -> None:
        base = {
            "label": "task",
            "policy": c.policy_to_dict(c.Policy(("src/**",), limits=c.Limits(3, 4, 5, 6, 7))),
        }
        blocked = c.build_prompt(base, 1, None, None)
        self.assertIn("files <= 3", blocked)
        self.assertIn("working bytes <= 6", blocked)
        self.assertIn("Do not commit.", blocked)
        allowed_config = {
            **base,
            "policy": c.policy_to_dict(c.Policy(("src/**",), limits=c.Limits(3, 4, 5, 6, 7), allow_commits=True)),
        }
        allowed = c.build_prompt(allowed_config, 2, None, None)
        self.assertIn("Commits are allowed by this envelope.", allowed)
        self.assertNotIn("Do not commit.", allowed)

    def test_invalid_claude_configs(self) -> None:
        bad = [
            {"binary": "", "max_turns": 1, "timeout_seconds": 1, "max_budget_usd": None},
            {"binary": "x", "max_turns": 0, "timeout_seconds": 1, "max_budget_usd": None},
            {"binary": "x", "max_turns": 1, "timeout_seconds": 0, "max_budget_usd": None},
            {"binary": "x", "max_turns": 1, "timeout_seconds": float("nan"), "max_budget_usd": None},
            {"binary": "x", "max_turns": 1, "timeout_seconds": float("inf"), "max_budget_usd": None},
            {"binary": "x", "max_turns": 1, "timeout_seconds": 1, "max_budget_usd": 0},
            {"binary": "x", "max_turns": 1, "timeout_seconds": 1, "max_budget_usd": float("nan")},
            {"binary": "x", "max_turns": 1, "timeout_seconds": 1, "max_budget_usd": float("inf")},
            {"binary": "x", "max_turns": 1, "timeout_seconds": 1, "max_budget_usd": None, "model": ""},
            {"binary": "x", "max_turns": 1, "timeout_seconds": 1, "max_budget_usd": None, "effort": 1},
            {"binary": "x", "max_turns": 1, "timeout_seconds": 1, "max_budget_usd": None, "effort": "turbo"},
        ]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(c.PolicyError): c._validate_claude_config(item)

    def test_arm_invalid_inputs(self) -> None:
        for kwargs in [
            {"label": "", "policy": self.policy},
            {"label": "x" * (c.MAX_LABEL_LENGTH + 1), "policy": self.policy},
            {"label": "x", "policy": self.policy, "mode": "bad"},
            {"label": "x", "policy": self.policy, "max_attempts": 0},
            {"label": "x", "policy": self.policy, "verify": ["'"]},
            {"label": "x", "policy": self.policy, "verify": ["   "]},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(c.CordonError):
                c.arm_session(self.fx.root, **kwargs)
        (self.fx.root / "README.md").write_text("dirty\n")
        with self.assertRaises(c.RepositoryError): c.arm_session(self.fx.root, label="x", policy=self.policy)

    def test_double_arm(self) -> None:
        c.arm_session(self.fx.root, label="x", policy=self.policy)
        with self.assertRaises(c.StateError): c.arm_session(self.fx.root, label="x", policy=self.policy)


class ResumeAndEngineTests(Base):
    def _env(self, actions):
        env = self.fx.sequence(actions); old = os.environ.copy(); os.environ.update(env)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))

    def test_manual_resume_and_accepted_resume_rejected(self) -> None:
        c.arm_session(self.fx.root, label="x", policy=self.policy)
        with self.assertRaises(c.StateError): c.resume_claude_session(self.fx.root)
        c.reset_session(self.fx.root)
        self._env([{"write": {"src/app.py": "ok\n"}}])
        c.run_claude_session(self.fx.root, label="x", policy=self.policy, claude=self.fx.claude_config())
        with self.assertRaises(c.StateError): c.resume_claude_session(self.fx.root)

    def test_resume_refuses_out_of_scope_partial_change(self) -> None:
        c.arm_session(self.fx.root, label="x", policy=self.policy, mode="claude", claude=self.fx.claude_config())
        (self.fx.root / "README.md").write_text("bad\n")
        with self.assertRaises(c.PolicyError): c.resume_claude_session(self.fx.root)
        self.assertEqual(c.session_status(self.fx.root)["phase"], "rejected")

    def test_attempt_limit(self) -> None:
        config, state = c.arm_session(self.fx.root, label="x", policy=self.policy, mode="claude", max_attempts=1, claude=self.fx.claude_config())
        state["attempt"] = 1; c.save_state(self.fx.root, state)
        with self.assertRaises(c.StateError): c.resume_claude_session(self.fx.root)

    def test_timeout_and_output_limit_states(self) -> None:
        self._env([{"sleep": 1}, {"stdout_bytes": 5000}])
        cfg = self.fx.claude_config(); cfg["timeout_seconds"] = 0.04
        p1, _ = c.run_claude_session(self.fx.root, label="x", policy=self.policy, claude=cfg)
        self.assertTrue(p1.timed_out)
        c.reset_session(self.fx.root)
        run("git", "checkout", "--", ".", cwd=self.fx.root)
        self._env([{"stdout_bytes": 5000, "sleep": 0.2}])
        cfg["timeout_seconds"] = 3
        p2, _ = c.run_claude_session(self.fx.root, label="x", policy=self.policy, claude=cfg, output_cap=64)
        self.assertTrue(p2.output_limited)

    def test_run_holds_repository_lock_for_entire_agent_attempt(self) -> None:
        self._env([{"sleep": 0.35}])
        result_box: list[tuple[c.ProcessResult, c.AuditResult]] = []
        error_box: list[BaseException] = []

        def worker() -> None:
            try:
                result_box.append(
                    c.run_claude_session(
                        self.fx.root,
                        label="concurrent",
                        policy=self.policy,
                        claude=self.fx.claude_config(),
                    )
                )
            except BaseException as exc:
                error_box.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        index_path = self.fx.root / "fake-sequence.index"
        deadline = time.monotonic() + 2.0
        while not index_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(index_path.exists(), "fake Claude did not start before the concurrency deadline")
        self.assertTrue((self.fx.root / ".git" / "cordon.lock").exists())
        self.assertFalse((self.fx.root / ".cordon" / "lock").exists())
        with self.assertRaises(c.LockError):
            c.check_session(self.fx.root)
        thread.join(timeout=3.0)
        self.assertFalse(thread.is_alive(), "agent thread did not finish")
        self.assertEqual(error_box, [])
        self.assertEqual(len(result_box), 1)
        self.assertTrue(result_box[0][1].passed)

    def test_keyboard_interrupt_is_persisted(self) -> None:
        config, state = c.arm_session(self.fx.root, label="x", policy=self.policy, mode="claude", claude=self.fx.claude_config())
        with mock.patch.object(c, "run_bounded_process", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                c._run_agent_attempt(self.fx.root, config, state, self.policy, output_cap=100)
        self.assertEqual(c.session_status(self.fx.root)["phase"], "interrupted")

    def test_non_interrupt_exception_bubbles(self) -> None:
        config, state = c.arm_session(self.fx.root, label="x", policy=self.policy, mode="claude", claude=self.fx.claude_config())
        with mock.patch.object(c, "run_bounded_process", side_effect=c.ProcessError("x")), self.assertRaises(c.ProcessError):
            c._run_agent_attempt(self.fx.root, config, state, self.policy, output_cap=100)

    def test_reset_absent_is_noop(self) -> None:
        c.reset_session(self.fx.root)
        self.assertFalse((self.fx.root / ".cordon").exists())

class BranchCoverageTests(Base):
    def test_forced_sigkill_branch_without_timing_race(self) -> None:
        class Proc:
            pid = 424242
            def poll(self): return None
            def wait(self, timeout=None): return 0
        proc = Proc()
        with mock.patch.object(c.os, "killpg") as killpg:
            c._terminate_process_group(proc, grace_seconds=0)  # type: ignore[arg-type]
        self.assertEqual([call.args[1] for call in killpg.call_args_list], [signal.SIGTERM, signal.SIGKILL])

    def test_output_limit_branch_without_scheduler_race(self) -> None:
        class Proc:
            pid = 424243
            returncode = -signal.SIGTERM
            stdout = io.BytesIO(b"abcdef")
            stderr = io.BytesIO(b"")
            def poll(self): return None
        class ImmediateThread:
            def __init__(self, target, args, daemon): self.target=target; self.args=args
            def start(self): self.target(*self.args)
            def join(self, timeout=None): pass
            def is_alive(self): return False
        with mock.patch.object(c.subprocess, "Popen", return_value=Proc()), \
             mock.patch.object(c.threading, "Thread", ImmediateThread), \
             mock.patch.object(c, "_terminate_process_group") as terminate:
            result = c.run_bounded_process(["fake"], cwd=Path.cwd(), timeout=1, output_cap=2)
        self.assertTrue(result.output_limited)
        terminate.assert_called_once()

    def test_audit_rare_git_visible_file_kinds(self) -> None:
        baseline = c.current_head(self.fx.root)
        policy = c.Policy(("**",), limits=c.Limits(20, 100, 100, 100000, 20))
        # A tracked binary exercises numstat's '-'/'-' accounting branch.
        (self.fx.root / "src/app.py").write_bytes(b"\x00changed")
        audit = c.audit_policy(self.fx.root, baseline, policy)
        self.assertGreaterEqual(audit.binary_files, 1)

        # Deterministically exercise preflight races/types that are otherwise
        # filesystem-scheduler dependent.
        with mock.patch.object(c, "_git_visible_changes", return_value=({}, {b"gone", b"link", b"special"})), \
             mock.patch.object(c.os, "lstat") as lstat_mock, \
             mock.patch.object(c.os, "readlink", return_value="target"), \
             mock.patch.object(c, "_measure_untracked") as measure:
            def fake_lstat(path):
                name = Path(path).name
                if name == "gone": raise FileNotFoundError(name)
                if name == "link": return mock.Mock(st_mode=0o120777, st_size=6)
                return mock.Mock(st_mode=0o040755, st_size=0)
            lstat_mock.side_effect = fake_lstat
            measure.side_effect = [
                (0, 0, False, "untracked path disappeared during audit", 0),
                (6, 1, False, None, 0),
                (0, 0, False, "untracked path is not a regular file or symlink", 0),
            ]
            mocked = c.audit_policy(self.fx.root, baseline, policy)
        self.assertTrue(any("disappeared" in item for item in mocked.violations))
        self.assertTrue(any("not a regular" in item for item in mocked.violations))


class IndexFlagTests(Base):
    """`assume-unchanged` and `skip-worktree` hide worktree edits from `git diff`."""

    def _arm(self) -> None:
        c.arm_session(self.fx.root, label="envelope", policy=self.policy)

    def test_clean_repository_reports_no_hidden_paths(self) -> None:
        self.assertEqual(c.index_hidden_paths(self.fx.root), ())

    def test_arm_refuses_while_assume_unchanged_is_set(self) -> None:
        run("git", "update-index", "--assume-unchanged", "README.md", cwd=self.fx.root)
        with self.assertRaises(c.RepositoryError) as ctx:
            self._arm()
        self.assertIn("README.md", str(ctx.exception))
        self.assertIn("--no-assume-unchanged", str(ctx.exception))
        self.assertFalse(c.state_dir(self.fx.root).exists())

    def test_assume_unchanged_after_arming_is_a_violation(self) -> None:
        self._arm()
        run("git", "update-index", "--assume-unchanged", "README.md", cwd=self.fx.root)
        (self.fx.root / "README.md").write_text("smuggled\n", encoding="utf-8")
        audit = c.check_session(self.fx.root)
        self.assertFalse(audit.passed)
        self.assertTrue(any("hidden from the audit" in item for item in audit.violations))

    def test_skip_worktree_after_arming_is_a_violation(self) -> None:
        self._arm()
        run("git", "update-index", "--skip-worktree", "README.md", cwd=self.fx.root)
        (self.fx.root / "README.md").write_text("smuggled\n", encoding="utf-8")
        audit = c.check_session(self.fx.root)
        self.assertFalse(audit.passed)
        self.assertTrue(any("hidden from the audit" in item for item in audit.violations))

    def test_hidden_path_report_is_bounded(self) -> None:
        names = [f"src/mod{index}.py" for index in range(c.MAX_HIDDEN_PATHS_REPORTED + 3)]
        for name in names:
            (self.fx.root / name).write_text("X = 1\n", encoding="utf-8")
        run("git", "add", ".", cwd=self.fx.root)
        run("git", "commit", "-q", "-m", "many modules", cwd=self.fx.root)
        run("git", "update-index", "--skip-worktree", *names, cwd=self.fx.root)
        hidden = c.index_hidden_paths(self.fx.root)
        self.assertEqual(len(hidden), len(names))
        message = c._hidden_path_remedy(hidden)
        self.assertIn("(+3 more)", message)
        self.assertEqual(message.count("src/mod"), c.MAX_HIDDEN_PATHS_REPORTED)

    def test_non_utf8_hidden_path_survives_reporting(self) -> None:
        raw = b"src/weird-\xff.bin"
        if create_non_utf8_file(self.fx.root / "src", b"weird-\xff.bin", b"payload\n") is None:
            self.assertIn("weird-", c._hidden_path_remedy((raw,)))
            self.skipTest("filesystem rejects non-UTF-8 filenames")
        run("git", "add", "-A", cwd=self.fx.root)
        run("git", "commit", "-q", "-m", "byte path", cwd=self.fx.root)
        subprocess.run(["git", "update-index", "--skip-worktree", os.fsdecode(raw)],
                       cwd=self.fx.root, check=True)
        hidden = c.index_hidden_paths(self.fx.root)
        self.assertIn(raw, hidden)
        self.assertIn("weird-", c._hidden_path_remedy(hidden))

    def test_malformed_ls_files_record_is_rejected(self) -> None:
        with mock.patch.object(c, "_git", return_value=b"S\x00"):
            with self.assertRaises(c.RepositoryError):
                c.index_hidden_paths(self.fx.root)
