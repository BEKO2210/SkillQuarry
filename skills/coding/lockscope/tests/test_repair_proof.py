"""The repair proved by running the program, not by reading it.

Four tasks take one mutex and then wait on a four-party barrier. The first task
holds the lock while the barrier waits for three tasks that can never reach it,
so the program deadlocks and exits 3 on its own timeout. After LockScope moves
the acquisition past the barrier the same program completes.

Detection, repair, re-analysis, compilation, execution and the unsafe delta are
all checked, because a repair that clears a finding and breaks the program is
not a repair.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness import CONTENTION, TempCrate, require, run

from lockscope import engine, repair, report, syntax


class ContentionRepairTests(unittest.TestCase):
    crate: Path

    @classmethod
    def setUpClass(cls) -> None:
        require(rust_analyzer=True, cargo=True)
        from lockscope.semantics import RustAnalyzerResolver

        cls.temp = tempfile.TemporaryDirectory()
        cls.copy = TempCrate(CONTENTION, Path(cls.temp.name) / "contention")
        cls.crate = cls.copy.__enter__()
        main = cls.crate / "src" / "main.rs"

        cls.before_source = main.read_bytes()
        cls.before_unsafe = cls.before_source.count(b"unsafe")
        with RustAnalyzerResolver(cls.crate) as resolver:
            cls.before = engine.analyze([main], resolver, cls.crate)
        cls.before_run = run(["cargo", "run", "--quiet"], cls.crate, timeout=600)

        cls.repair, cls.refusals = repair.repair_file(main, "src/main.rs")
        cls.after_source = main.read_bytes()

        with RustAnalyzerResolver(cls.crate) as resolver:
            cls.after = engine.analyze([main], resolver, cls.crate)
        cls.after_run = run(["cargo", "run", "--quiet"], cls.crate, timeout=600)
        cls.after_clippy = run(
            ["cargo", "clippy", "--quiet", "--all-targets", "--", "-D", "warnings"],
            cls.crate, timeout=900,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.copy.__exit__(None, None, None)
        cls.temp.cleanup()

    def test_1_the_deadlock_is_detected_before_the_repair(self):
        kinds = {f["kind"] for f in self.before.findings}
        self.assertIn("exclusive_lock_across_await", kinds)

    def test_2_the_program_really_does_hang(self):
        """Exit code 3 is the program's own timeout, not the test's patience."""
        self.assertEqual(self.before_run.returncode, 3, self.before_run.stdout[-500:])

    def test_3_a_repair_is_generated(self):
        self.assertIsNotNone(self.repair)
        self.assertEqual(self.repair.guard, "guard")

    def test_4_the_acquisition_now_follows_the_barrier(self):
        text = self.after_source.decode()
        self.assertLess(text.index("barrier.wait().await;"), text.index("let mut guard"))

    def test_5_the_finding_is_cleared(self):
        kinds = {f["kind"] for f in self.after.findings}
        self.assertNotIn("exclusive_lock_across_await", kinds)
        self.assertEqual(report.verdict_for(self.after), report.PASS)

    def test_6_the_program_now_completes(self):
        self.assertEqual(self.after_run.returncode, 0, self.after_run.stdout[-500:])

    def test_7_the_repaired_program_still_satisfies_strict_clippy(self):
        self.assertEqual(
            self.after_clippy.returncode, 0,
            (self.after_clippy.stdout + self.after_clippy.stderr)[-1500:],
        )

    def test_8_no_unsafe_was_introduced(self):
        self.assertEqual(self.after_source.count(b"unsafe"), self.before_unsafe)

    def test_9_the_repaired_file_parses_cleanly(self):
        errors = [n for n in syntax.walk(syntax.parse(self.after_source).root_node)
                  if n.type == "ERROR" or n.is_missing]
        self.assertEqual(errors, [])

    def test_10_nothing_but_the_acquisition_moved(self):
        """The diff is one line out and one line in — nothing else changed."""
        before = self.before_source.decode().splitlines()
        after = self.after_source.decode().splitlines()
        self.assertEqual(sorted(before), sorted(after))
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
