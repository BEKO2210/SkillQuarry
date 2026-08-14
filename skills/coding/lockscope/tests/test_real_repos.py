"""Three real repositories, at pinned commits.

Two of them are historical oracles: a maintainer already fixed a lock that was
held across an await, so LockScope must see the problem in the older commit and
see it gone in the newer one, without inventing anything in either. The third is
a healthy repository into which a known fault is injected; the compiler, the
analysis and the repair are then all asked independently.

Commits are pinned. Evidence that moves when someone pushes to a branch is not
evidence. This suite clones over the network and builds Rust, so it is opt-in:
`--real` on the runner, or `LOCKSCOPE_REAL_REPOS=1`.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from harness import require, run

from lockscope import engine, repair, verify

JAVIS = ("https://github.com/BEKO2210/Javis.git",
         "f0d6b556f459a3757b15e13fde3f5198b7d0826e",
         "26f6e5db1d47af58e814809505929fa0c16ae1eb",
         Path("crates/viz/src/state.rs"))
FERRYMAN = ("https://github.com/iMMIQ/ferryman.git",
            "8e9697b9eeee9db1e93a7e22eb7572650f5b001d",
            "93b814fca8c6aca98e0f2a0859545b3ada4945a8",
            Path("src/bin/ferryman-web.rs"))
MINI_REDIS = ("https://github.com/tokio-rs/mini-redis.git",
              "3d93b42bc363220f85af4fc9e1bebd35b588a4a3",
              Path("src/db.rs"))

# The fault injected into mini-redis: a std guard taken, then an await, then a
# use of the guard. It is a real mistake, not a syntactic trap.
INJECTION_TARGET = """        } else {
            // There are no keys expiring in the future. Wait until the task is
            // notified.
            shared.background_task.notified().await;
        }
"""
INJECTION = """        } else {
            // There are no keys expiring in the future. Wait until the task is
            // notified.
            let state = shared.state.lock().unwrap();
            shared.background_task.notified().await;
            if state.shutdown {
                break;
            }
        }
"""

ENABLED = os.environ.get("LOCKSCOPE_REAL_REPOS") == "1"


def clone(url: str, commit: str, into: Path) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    for argv in (
        ["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(into)],
        ["git", "fetch", "--quiet", "origin", commit],
        ["git", "checkout", "--quiet", "--detach", commit],
    ):
        finished = run(argv, into if argv[1] != "clone" else into.parent, timeout=600)
        if finished.returncode != 0:
            raise unittest.SkipTest(f"{' '.join(argv)} failed: {finished.stderr[-300:]}")
    return into


def analyse(root: Path, relative: Path) -> engine.Analysis:
    from lockscope.semantics import RustAnalyzerResolver

    with RustAnalyzerResolver(root, warmup_timeout=180) as resolver:
        return engine.analyze([root / relative], resolver, root)


@unittest.skipUnless(ENABLED, "set LOCKSCOPE_REAL_REPOS=1 to run against real repositories")
class HistoricalOracleTests(unittest.TestCase):
    """A fix that a human made is the answer key."""

    @classmethod
    def setUpClass(cls) -> None:
        require(rust_analyzer=True, cargo=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="lockscope-real-")
        root = Path(cls.temp.name)
        url, before, after, path = JAVIS
        cls.javis_before = analyse(clone(url, before, root / "javis-before"), path)
        cls.javis_after = analyse(clone(url, after, root / "javis-after"), path)
        url, before, after, path = FERRYMAN
        cls.ferry_before = analyse(clone(url, before, root / "ferry-before"), path)
        cls.ferry_after = analyse(clone(url, after, root / "ferry-after"), path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_javis_held_an_exclusive_lock_across_an_await(self):
        self.assertIn("exclusive_lock_across_await", self.javis_before.kinds_in("run_recall"))

    def test_javis_no_longer_does(self):
        self.assertNotIn("exclusive_lock_across_await", self.javis_after.kinds_in("run_recall"))

    def test_javis_still_shows_the_read_guard_that_remained(self):
        """The maintainer's fix narrowed the exclusive lock and left a read
        guard in place. Reporting it gone would be flattering, not accurate."""
        self.assertIn("read_lock_across_await", self.javis_after.kinds_in("run_recall"))

    def test_no_cycle_is_invented_in_either_javis_commit(self):
        self.assertEqual(self.javis_before.cycles, [])
        self.assertEqual(self.javis_after.cycles, [])

    def test_ferryman_held_locks_across_awaits_in_two_functions(self):
        self.assertIn("exclusive_lock_across_await", self.ferry_before.kinds_in("mutate_job"))
        self.assertIn("exclusive_lock_across_await", self.ferry_before.kinds_in("claim_queued_job"))

    def test_ferryman_cleared_both(self):
        self.assertNotIn("exclusive_lock_across_await", self.ferry_after.kinds_in("mutate_job"))
        self.assertNotIn("exclusive_lock_across_await", self.ferry_after.kinds_in("claim_queued_job"))

    def test_no_cycle_is_invented_in_either_ferryman_commit(self):
        self.assertEqual(self.ferry_before.cycles, [])
        self.assertEqual(self.ferry_after.cycles, [])


@unittest.skipUnless(ENABLED, "set LOCKSCOPE_REAL_REPOS=1 to run against real repositories")
class InjectedFaultTests(unittest.TestCase):
    """A healthy repository, a real fault, and three independent judges."""

    @classmethod
    def setUpClass(cls) -> None:
        require(rust_analyzer=True, cargo=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="lockscope-mini-")
        url, commit, relative = MINI_REDIS
        cls.repo = clone(url, commit, Path(cls.temp.name) / "mini-redis")
        cls.path = cls.repo / relative

        cls.baseline_check = verify.cargo_check(cls.repo)
        cls.baseline_test = verify.cargo_test(cls.repo)
        cls.baseline_clippy = verify.clippy(cls.repo)
        cls.healthy = analyse(cls.repo, relative)

        text = cls.path.read_text("utf-8")
        if text.count(INJECTION_TARGET) != 1:
            raise AssertionError("the pinned mini-redis source no longer matches the injection site")
        cls.path.write_text(text.replace(INJECTION_TARGET, INJECTION), "utf-8")
        cls.injected_source = cls.path.read_bytes()
        cls.injected = analyse(cls.repo, relative)
        cls.injected_check = verify.cargo_check(cls.repo)

        cls.repair, _ = repair.repair_file(cls.path, relative.as_posix())
        cls.repaired_source = cls.path.read_bytes()
        cls.repaired = analyse(cls.repo, relative)
        cls.repaired_check = verify.cargo_check(cls.repo)
        cls.repaired_test = verify.cargo_test(cls.repo)
        cls.repaired_clippy = verify.clippy(cls.repo)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_1_the_untouched_repository_builds_and_passes_its_tests(self):
        self.assertTrue(self.baseline_check.passed, self.baseline_check.output_tail)
        self.assertTrue(self.baseline_test.passed, self.baseline_test.output_tail)

    def test_2_the_untouched_repository_holds_no_lock_across_an_await(self):
        """Nothing dangerous, and no cycle, in the untouched repository.

        `Db::set` does hold an exclusive guard across 53 lines, and LockScope
        says so as an advisory with `heuristic` confidence. That is a true
        statement about the code — the section really is that long — and it is
        not a claim that anything is wrong, so it does not make the baseline
        unhealthy. What would make it unhealthy is a guard held across an await
        or an ordering cycle, and there are none.
        """
        dangerous = [f for f in self.healthy.findings
                     if f["kind"] != "large_exclusive_critical_section"]
        self.assertEqual(dangerous, [])
        self.assertEqual(self.healthy.cycles, [])
        for finding in self.healthy.findings:
            self.assertEqual(finding["severity"], "advisory")
            self.assertEqual(finding["confidence"], "heuristic")

    def test_3_the_injected_fault_is_detected(self):
        self.assertIn("sync_lock_across_await", self.injected.kinds_in("purge_expired_tasks"))

    def test_4_the_compiler_rejects_the_injected_fault_independently(self):
        """A second opinion that owes nothing to this tool's analysis."""
        self.assertFalse(self.injected_check.passed)
        self.assertIn("Send", self.injected_check.output_tail)

    def test_5_a_repair_is_generated(self):
        self.assertIsNotNone(self.repair)

    def test_6_the_acquisition_moved_after_the_independent_await(self):
        text = self.repaired_source.decode()
        self.assertLess(text.index("background_task.notified().await;"),
                        text.index("let state = shared.state.lock().unwrap();"))

    def test_7_the_finding_is_cleared(self):
        self.assertNotIn("sync_lock_across_await", self.repaired.kinds_in("purge_expired_tasks"))

    def test_8_the_repaired_repository_builds_and_passes_its_tests(self):
        self.assertTrue(self.repaired_check.passed, self.repaired_check.output_tail)
        self.assertTrue(self.repaired_test.passed, self.repaired_test.output_tail)

    def test_9_clippy_is_judged_against_its_own_baseline(self):
        """This pinned commit already fails strict Clippy on Rust 1.97.

        Demanding a clean run would either fail honest work or invite quietly
        lowering the bar; the comparison is therefore baseline-relative, and the
        baseline is recorded rather than assumed.
        """
        comparison = verify.clippy_regression(self.baseline_clippy, self.repaired_clippy)
        self.assertFalse(comparison["regressed"], comparison)

    def test_10_no_unsafe_was_introduced(self):
        self.assertEqual(self.repaired_source.count(b"unsafe"), self.injected_source.count(b"unsafe"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
