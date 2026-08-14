"""The repair, and — more importantly — everything it refuses to do.

A repair that is willing to move code across a branch, past a use of the guard,
or out of its scope would be worse than no repair at all. Most of these tests
exist to prove the tool stops.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness import source

from lockscope import repair, syntax


class MotionTests(unittest.TestCase):
    def repair(self, text: str):
        return repair.repair_source(source(text), "lib.rs")

    def test_the_acquisition_moves_after_the_independent_await(self):
        out, made, _ = self.repair("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    independent().await;
    guard.push(1);
}
""")
        self.assertIsNotNone(made)
        self.assertEqual(out.decode().splitlines()[1:4], [
            "    independent().await;",
            "    let mut guard = state.lock().await;",
            "    guard.push(1);",
        ])

    def test_a_multiline_acquisition_keeps_its_shape(self):
        out, made, _ = self.repair("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state
        // still readable afterwards
        .lock()
        .await;
    independent().await;
    guard.push(1);
}
""")
        self.assertIsNotNone(made)
        text = out.decode()
        self.assertIn("// still readable afterwards", text)
        self.assertLess(text.index("independent().await;"), text.index("let mut guard"))

    def test_the_repaired_file_still_parses(self):
        out, made, _ = self.repair("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    independent().await;
    guard.push(1);
}
""")
        self.assertIsNotNone(made)
        errors = [n for n in syntax.walk(syntax.parse(out).root_node) if n.type == "ERROR"]
        self.assertEqual(errors, [])

    def test_the_last_independent_await_is_the_target(self):
        out, made, _ = self.repair("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    first().await;
    second().await;
    guard.push(1);
}
""")
        lines = out.decode().splitlines()
        self.assertEqual(lines[3].strip(), "let mut guard = state.lock().await;")
        self.assertEqual(made.to_line, 4)


class RefusalTests(unittest.TestCase):
    def refuse(self, text: str) -> list[str]:
        out, made, refusals = repair.repair_source(source(text), "lib.rs")
        self.assertIsNone(made, "expected no repair")
        self.assertEqual(out, source(text), "the file must be left alone")
        return [item.reason for item in refusals]

    def test_it_refuses_when_the_guard_is_used_before_the_await(self):
        reasons = self.refuse("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    guard.push(0);
    independent().await;
    guard.push(1);
}
""")
        self.assertIn("no independent await between the acquisition and the guard's first use", reasons)

    def test_it_refuses_to_move_across_a_branch(self):
        reasons = self.refuse("""
async fn work(state: &Mutex<Vec<u8>>, flag: bool) {
    let mut guard = state.lock().await;
    if flag {
        independent().await;
    }
    guard.push(1);
}
""")
        self.assertIn("an await inside branching control flow", reasons)

    def test_it_refuses_to_move_across_a_loop(self):
        reasons = self.refuse("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    while ready().await {
        step();
    }
    guard.push(1);
}
""")
        self.assertIn("an await inside branching control flow", reasons)

    def test_it_refuses_when_the_guard_is_returned_early(self):
        reasons = self.refuse("""
async fn work(state: &Mutex<Vec<u8>>, bail: bool) -> usize {
    let guard = state.lock().await;
    if bail {
        return guard.len();
    }
    independent().await;
    guard.len()
}
""")
        self.assertTrue(reasons)

    def test_a_guard_that_is_not_held_across_an_await_is_left_alone(self):
        out, made, refusals = repair.repair_source(source("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    guard.push(1);
}
"""), "lib.rs")
        self.assertIsNone(made)
        self.assertEqual(refusals, [])

    def test_a_guard_in_an_inner_scope_is_not_moved_out_of_it(self):
        out, made, _ = repair.repair_source(source("""
async fn work(state: &Mutex<Vec<u8>>) -> usize {
    let n = {
        let guard = state.lock().await;
        guard.len()
    };
    independent().await;
    n
}
"""), "lib.rs")
        self.assertIsNone(made)


class FileTests(unittest.TestCase):
    def test_a_repaired_file_is_written_once(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lib.rs"
            path.write_bytes(source("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    independent().await;
    guard.push(1);
}
"""))
            made, _ = repair.repair_file(path)
            self.assertIsNotNone(made)
            first = path.read_bytes()
            again, _ = repair.repair_file(path)
            self.assertIsNone(again, "a repaired file must not be repaired again")
            self.assertEqual(path.read_bytes(), first)

    def test_the_file_is_untouched_when_nothing_is_safe_to_do(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lib.rs"
            original = source("""
async fn work(state: &Mutex<Vec<u8>>, flag: bool) {
    let mut guard = state.lock().await;
    if flag {
        independent().await;
    }
    guard.push(1);
}
""")
            path.write_bytes(original)
            made, refusals = repair.repair_file(path)
            self.assertIsNone(made)
            self.assertEqual(path.read_bytes(), original)
            self.assertTrue(refusals)


class SafetyTests(unittest.TestCase):
    def test_unsafe_is_never_introduced(self):
        """The rule is checked in the code, not only in the documentation."""
        out, made, _ = repair.repair_source(source("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    independent().await;
    guard.push(1);
}
"""), "lib.rs")
        self.assertNotIn(b"unsafe", out)

    def test_an_existing_unsafe_block_is_carried_through_unchanged(self):
        before = source("""
async fn work(state: &Mutex<Vec<u8>>) {
    let mut guard = state.lock().await;
    independent().await;
    unsafe { touch() };
    guard.push(1);
}
""")
        out, made, _ = repair.repair_source(before, "lib.rs")
        self.assertIsNotNone(made)
        self.assertEqual(out.count(b"unsafe"), before.count(b"unsafe"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
