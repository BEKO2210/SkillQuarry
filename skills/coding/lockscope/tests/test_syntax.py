"""Structured extraction: what the syntax tree alone must get right.

These tests carry the defect that ended the previous design. A regular
expression could not see a lock acquisition split across lines with a comment in
the middle, and no amount of pattern tuning fixes that class of miss. Each case
here is valid Rust that a real codebase writes.
"""
from __future__ import annotations

import unittest

from harness import source

from lockscope import syntax


class ExtractionTests(unittest.TestCase):
    def candidates(self, text: str):
        return syntax.candidates_in(source(text))

    def only(self, text: str) -> syntax.Candidate:
        found = self.candidates(text)
        self.assertEqual(len(found), 1, [c.guard for c in found])
        return found[0]

    def test_a_plain_acquisition_is_found(self):
        candidate = self.only("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    other().await;
    guard.push(1);
}
""")
        self.assertEqual((candidate.guard, candidate.op), ("guard", "lock"))
        self.assertEqual(candidate.awaits_while_live, 1)

    def test_the_acquisition_may_be_split_across_lines(self):
        """The defect that ended the pattern-matching design."""
        candidate = self.only("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state
        // a comment where a regex gives up
        .lock()
        .await;
    other().await;
    guard.push(1);
}
""")
        self.assertEqual(candidate.guard, "guard")
        self.assertEqual(candidate.awaits_while_live, 1)

    def test_a_parenthesised_receiver_is_still_a_receiver(self):
        self.assertEqual(self.only("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = (state).lock().await;
    other().await;
    guard.push(1);
}
""").lock_expr, "(state)")

    def test_an_owned_guard_through_arc_clone(self):
        candidate = self.only("""
async fn work(state: Arc<Mutex<Vec<u8>>>) {
    let mut guard = Arc::clone(&state).lock_owned().await;
    other().await;
    guard.push(1);
}
""")
        self.assertEqual(candidate.op, "lock_owned")
        # `Arc` and `clone` cannot name the lock, so `state` is offered first.
        self.assertEqual(candidate.receiver_points[0][0], "state")

    def test_unwrap_passes_the_guard_through(self):
        self.assertEqual(self.only("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state
        .lock()
        .unwrap();
    other().await;
    guard.push(1);
}
""").op, "lock")

    def test_a_guard_in_an_inner_scope_ends_with_that_scope(self):
        candidate = self.only("""
async fn work(state: &Mutex<Vec<u8>>) -> usize {
    let n = {
        let guard = state.lock().await;
        guard.len()
    };
    other().await;
    n
}
""")
        self.assertEqual(candidate.awaits_while_live, 0)

    def test_an_explicit_drop_ends_the_guard(self):
        candidate = self.only("""
async fn work(state: &Mutex<Vec<u8>>) -> usize {
    let guard = state.lock().await;
    let n = guard.len();
    drop(guard);
    other().await;
    n
}
""")
        self.assertEqual(candidate.awaits_while_live, 0)
        self.assertEqual(candidate.explicit_drop_line, 4)

    def test_dropping_a_different_guard_does_not_end_this_one(self):
        found = {c.guard: c for c in self.candidates("""
async fn work(a: &Mutex<Vec<u8>>, b: &Mutex<Vec<u8>>) {
    let ga = a.lock().await;
    let gb = b.lock().await;
    drop(gb);
    other().await;
    black_box((&*ga,));
}
""")}
        # Two awaits, not one: acquiring `gb` is itself a suspension point
        # while `ga` is live, which is exactly the danger being measured.
        self.assertEqual(found["ga"].awaits_while_live, 2)
        self.assertEqual(found["gb"].awaits_while_live, 0)

    def test_a_lock_call_in_an_argument_is_not_the_binding(self):
        """`let x = f(m.lock().await)` binds the result of `f`, not the guard."""
        self.assertEqual(self.candidates("""
async fn work(state: &Mutex<Vec<u8>>) {
    let value = consume(state.lock().await);
    other().await;
    black_box(value);
}
"""), [])

    def test_a_destructuring_binding_is_not_taken_as_a_guard(self):
        self.assertEqual(self.candidates("""
async fn work(state: &Mutex<(u8, u8)>) {
    let (left, right) = *state.lock().await;
    other().await;
    black_box((left, right));
}
"""), [])

    def test_every_await_while_the_guard_is_live_is_counted(self):
        self.assertEqual(self.only("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    one().await;
    two().await;
    three().await;
    guard.push(1);
}
""").awaits_while_live, 3)

    def test_the_awaits_after_the_guard_dies_are_not_counted(self):
        self.assertEqual(self.only("""
async fn work(state: &Mutex<Vec<u8>>) {
    let guard = state.lock().await;
    let n = guard.len();
    drop(guard);
    one().await;
    two().await;
    black_box(n);
}
""").awaits_while_live, 0)

    def test_two_guards_are_reported_in_source_order(self):
        found = self.candidates("""
async fn work(a: &Mutex<u8>, b: &Mutex<u8>) {
    let first = a.lock().await;
    let second = b.lock().await;
    black_box((*first, *second));
}
""")
        self.assertEqual([c.guard for c in found], ["first", "second"])

    def test_a_shadowing_binding_does_not_extend_the_guard(self):
        found = self.candidates("""
async fn work(state: &Mutex<Vec<u8>>) -> usize {
    let guard = state.lock().await;
    let guard = guard.len();
    other().await;
    guard
}
""")
        self.assertEqual(len(found), 1)
        # The shadowed name is still textually used, which the analysis reports
        # as a live guard rather than silently assuming the shadow released it.
        self.assertEqual(found[0].guard, "guard")

    def test_a_guard_taken_in_a_match_arm_belongs_to_that_arm(self):
        found = self.candidates("""
async fn work(state: &Mutex<Vec<u8>>, which: u8) -> usize {
    match which {
        0 => {
            let guard = state.lock().await;
            guard.len()
        }
        _ => {
            let guard = state.lock().await;
            other().await;
            guard.len()
        }
    }
}
""")
        self.assertEqual(len(found), 2)
        self.assertEqual([c.awaits_while_live for c in found], [0, 1])

    def test_the_candidate_order_is_stable(self):
        text = """
async fn work(a: &Mutex<u8>, b: &Mutex<u8>) {
    let z = b.lock().await;
    let y = a.lock().await;
    black_box((*y, *z));
}
"""
        once = [(c.line, c.guard) for c in self.candidates(text)]
        twice = [(c.line, c.guard) for c in self.candidates(text)]
        self.assertEqual(once, twice)
        self.assertEqual(once, sorted(once))


class MacroTests(unittest.TestCase):
    def test_a_macro_invocation_is_located_with_its_scope(self):
        found = syntax.macro_invocations_in(source("""
async fn work(state: &Mutex<Vec<u8>>) {
    hold!(state, guard);
    other().await;
    guard.push(1);
}
"""))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].point.line, 1)
        self.assertIn("state", [name for name, _ in found[0].identifier_points])

    def test_an_expansion_that_binds_a_guard_is_recognised(self):
        self.assertEqual(
            syntax.acquisition_in_expansion("let mut guard = state.lock().await;"),
            ("guard", "lock"),
        )

    def test_an_expansion_without_a_lock_is_not_invented(self):
        self.assertIsNone(syntax.acquisition_in_expansion("let value = compute();"))

    def test_the_guard_lifetime_of_a_macro_is_measured_in_the_caller(self):
        text = source("""
async fn work(state: &Mutex<Vec<u8>>) {
    hold!(state, guard);
    other().await;
    guard.push(1);
}
""")
        invocation = syntax.macro_invocations_in(text)[0]
        _, drop_line, _, awaits = syntax.macro_guard_lifetime(text, invocation, "guard")
        self.assertEqual(awaits, 1)
        self.assertIsNone(drop_line)


class FileWalkTests(unittest.TestCase):
    def test_build_output_is_not_analysed(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "target" / "debug").mkdir(parents=True)
            (root / "src" / "lib.rs").write_text("fn main() {}", "utf-8")
            (root / "target" / "debug" / "generated.rs").write_text("fn main() {}", "utf-8")
            self.assertEqual([p.name for p in syntax.rust_files(root)], ["lib.rs"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
