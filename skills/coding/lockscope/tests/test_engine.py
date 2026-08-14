"""Classification, lock order and findings, with the semantics recorded.

A language server is not needed to test what the engine does with an answer —
only to obtain one. Recording the answers makes these tests fast, hermetic and
exact about the thing under test: a `.lock()` on a plain struct must never
become a finding, and a cycle must come from acquisitions that really nest.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from harness import source

from lockscope import engine, report, syntax
from lockscope.semantics import RecordedResolver

TOKIO = "file:///home/user/.cargo/registry/src/index.crates.io-1/tokio-1.47.1/src/sync/mutex.rs"
TOKIO_RW = "file:///home/user/.cargo/registry/src/index.crates.io-1/tokio-1.47.1/src/sync/rwlock.rs"
STD = "file:///rustc/abc/library/std/src/sync/mutex.rs"
PARKING = "file:///home/user/.cargo/registry/src/index.crates.io-1/parking_lot-0.12.4/src/mutex.rs"
PLAIN = "file:///home/user/project/src/lib.rs"


class ClassificationTests(unittest.TestCase):
    def test_a_tokio_mutex_is_an_async_exclusive_lock(self):
        self.assertEqual(engine.classify(TOKIO, "lock"), ("async", "exclusive"))

    def test_a_tokio_read_guard_is_a_read_lock(self):
        self.assertEqual(engine.classify(TOKIO_RW, "read"), ("async", "read"))

    def test_a_std_mutex_is_a_sync_lock(self):
        self.assertEqual(engine.classify(STD, "lock"), ("sync", "exclusive"))

    def test_a_parking_lot_mutex_is_a_sync_lock(self):
        self.assertEqual(engine.classify(PARKING, "lock"), ("sync", "exclusive"))

    def test_a_user_defined_lock_method_is_not_a_lock(self):
        """The whole reason semantics are resolved instead of names read."""
        self.assertIsNone(engine.classify(PLAIN, "lock"))

    def test_hover_text_alone_can_prove_the_family(self):
        self.assertEqual(
            engine.classify("```rust\nfn lock(&self) -> tokio::sync::MutexGuard<'_, T>\n```", "lock"),
            ("async", "exclusive"),
        )


class AnalysisTests(unittest.TestCase):
    def analyse(self, text: str, evidence: dict[str, str], **kwargs) -> engine.Analysis:
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "lib.rs"
            path.write_bytes(source(text))
            resolver = RecordedResolver(evidence, **kwargs)
            return engine.analyze([path], resolver, root)

    def test_a_sync_lock_across_an_await_is_critical(self):
        analysis = self.analyse("""
async fn work(state: &StdMutex<Vec<u8>>) {
    let mut guard = state.lock().unwrap();
    other().await;
    guard.push(1);
}
""", {"state": STD})
        self.assertEqual([f["kind"] for f in analysis.findings], ["sync_lock_across_await"])
        self.assertEqual(analysis.findings[0]["severity"], "critical")
        self.assertEqual(analysis.findings[0]["confidence"], "semantic")

    def test_an_async_exclusive_lock_across_an_await_is_high(self):
        analysis = self.analyse("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    other().await;
    guard.push(1);
}
""", {"state": TOKIO})
        self.assertEqual(analysis.findings[0]["kind"], "exclusive_lock_across_await")
        self.assertEqual(analysis.findings[0]["severity"], "high")

    def test_a_read_guard_across_an_await_is_medium(self):
        analysis = self.analyse("""
async fn work(state: &RwLock<Vec<u8>>) -> usize {
    let guard = state.read().await;
    other().await;
    guard.len()
}
""", {"state": TOKIO_RW})
        self.assertEqual(analysis.findings[0]["kind"], "read_lock_across_await")
        self.assertEqual(analysis.findings[0]["severity"], "medium")

    def test_a_guard_that_ends_before_the_await_is_no_finding(self):
        analysis = self.analyse("""
async fn work(state: &Mutex<Vec<u8>>) -> usize {
    let n = {
        let guard = state.lock().await;
        guard.len()
    };
    other().await;
    n
}
""", {"state": TOKIO})
        self.assertEqual(analysis.findings, [])
        self.assertEqual(len(analysis.lock_sites), 1)

    def test_a_fake_lock_produces_no_finding_and_is_reported_as_unresolved(self):
        analysis = self.analyse("""
async fn work(fake: &FakeMutex) {
    let guard = fake.lock().await;
    other().await;
    black_box(guard);
}
""", {"fake": PLAIN})
        self.assertEqual(analysis.findings, [])
        self.assertEqual(analysis.lock_sites, [])
        self.assertEqual(len(analysis.unresolved), 1)
        self.assertEqual(analysis.unresolved[0]["guard"], "guard")

    def test_a_wide_exclusive_section_without_an_await_is_only_advisory(self):
        body = "\n".join(f"    step_{i}();" for i in range(45))
        analysis = self.analyse(f"""
async fn work(state: &Mutex<Vec<u8>>) {{
    let mut guard = state.lock().await;
{body}
    guard.push(1);
}}
""", {"state": TOKIO})
        kinds = {f["kind"]: f for f in analysis.findings}
        self.assertIn("large_exclusive_critical_section", kinds)
        self.assertEqual(kinds["large_exclusive_critical_section"]["severity"], "advisory")
        self.assertEqual(kinds["large_exclusive_critical_section"]["confidence"], "heuristic")

    def test_the_report_is_byte_identical_across_runs(self):
        text = """
async fn work(a: &Mutex<u8>, b: &Mutex<u8>) {
    let ga = a.lock().await;
    let gb = b.lock().await;
    other().await;
    black_box((*ga, *gb));
}
"""
        first = report.dumps(report.build(self.analyse(text, {"a": TOKIO, "b": TOKIO}), {"rustc": "x"}))
        second = report.dumps(report.build(self.analyse(text, {"a": TOKIO, "b": TOKIO}), {"rustc": "x"}))
        self.assertEqual(first, second)


class LockOrderTests(unittest.TestCase):
    def site(self, function: str, line: int, key: str, expr: str, scope_end: int,
             drop_line: int | None = None) -> engine.LockSite:
        return engine.LockSite(
            file="lib.rs", function=function, line=line, guard=f"g{line}", lock_expr=expr,
            lock_key=key, family="async", mode="exclusive", origin="source",
            awaits_while_live=0, scope_end_line=scope_end, explicit_drop_line=drop_line,
            last_use_line=scope_end, span_lines=scope_end - line,
        )

    def test_two_functions_in_opposite_order_form_a_cycle(self):
        cycles = engine.find_cycles([
            self.site("ab", 2, "A", "self.a", 9),
            self.site("ab", 3, "B", "self.b", 9),
            self.site("ba", 12, "B", "self.b", 19),
            self.site("ba", 13, "A", "self.a", 19),
        ])
        self.assertEqual(cycles, [["self.a", "self.b"]])

    def test_a_consistent_order_is_not_a_cycle(self):
        cycles = engine.find_cycles([
            self.site("one", 2, "A", "self.a", 9),
            self.site("one", 3, "B", "self.b", 9),
            self.site("two", 12, "A", "self.a", 19),
            self.site("two", 13, "B", "self.b", 19),
        ])
        self.assertEqual(cycles, [])

    def test_three_locks_taken_in_a_ring_form_one_cycle(self):
        cycles = engine.find_cycles([
            self.site("ab", 2, "A", "self.a", 5), self.site("ab", 3, "B", "self.b", 5),
            self.site("bc", 8, "B", "self.b", 11), self.site("bc", 9, "C", "self.c", 11),
            self.site("ca", 14, "C", "self.c", 17), self.site("ca", 15, "A", "self.a", 17),
        ])
        self.assertEqual(cycles, [["self.a", "self.b", "self.c"]])

    def test_the_same_lock_taken_twice_is_a_self_cycle(self):
        cycles = engine.find_cycles([
            self.site("twice", 2, "A", "self.same", 6),
            self.site("twice", 3, "A", "self.same", 6),
        ])
        self.assertEqual(cycles, [["self.same"]])

    def test_a_guard_released_before_the_next_acquisition_makes_no_edge(self):
        cycles = engine.find_cycles([
            self.site("ab", 2, "A", "self.a", 9, drop_line=4),
            self.site("ab", 5, "B", "self.b", 9),
            self.site("ba", 12, "B", "self.b", 19, drop_line=14),
            self.site("ba", 15, "A", "self.a", 19),
        ])
        self.assertEqual(cycles, [])

    def test_locks_in_different_functions_alone_make_no_edge(self):
        cycles = engine.find_cycles([
            self.site("one", 2, "A", "self.a", 4),
            self.site("two", 12, "B", "self.b", 14),
        ])
        self.assertEqual(cycles, [])

    def test_a_cycle_is_reported_once_and_sorted(self):
        cycles = engine.find_cycles([
            self.site("ab", 2, "B", "self.b", 9), self.site("ab", 3, "A", "self.a", 9),
            self.site("ba", 12, "A", "self.a", 19), self.site("ba", 13, "B", "self.b", 19),
            self.site("ab2", 22, "B", "self.b", 29), self.site("ab2", 23, "A", "self.a", 29),
        ])
        self.assertEqual(cycles, [["self.a", "self.b"]])


class MacroSiteTests(unittest.TestCase):
    def test_a_guard_a_macro_created_becomes_a_lock_site(self):
        import tempfile

        text = source("""
async fn work(state: &Mutex<Vec<u8>>) {
    hold!(state, guard);
    other().await;
    guard.push(1);
}
""")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "lib.rs"
            path.write_bytes(text)
            resolver = RecordedResolver(
                {"state": TOKIO},
                expansions={1: "let mut guard = state.lock().await;"},
                functions={1: "work"},
            )
            analysis = engine.analyze([path], resolver, root)
        self.assertEqual([s.origin for s in analysis.lock_sites], ["macro"])
        self.assertEqual(analysis.findings[0]["kind"], "exclusive_lock_across_await")
        self.assertEqual(analysis.findings[0]["origin"], "macro")


if __name__ == "__main__":
    unittest.main(verbosity=2)
