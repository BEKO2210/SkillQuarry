"""Ground truth from the compiler, not from folklore.

The common advice is that `drop(guard)` before an await makes a future `Send`.
On the pinned toolchain it does not: the guard remains part of the generator
state and `tokio::spawn` still refuses the future. Ending the guard's lexical
scope does work. That is why LockScope's repair moves the acquisition instead of
inserting a `drop`, and these probes are how the claim stays honest — if a
future Rust release changes the behaviour, this suite fails and the guidance
gets revisited.
"""
from __future__ import annotations

import unittest

from harness import CASES, TempCrate, require, run

import tempfile
from pathlib import Path

PROBES = {
    "std_last_use": """
use std::hint::black_box;
use std::sync::{Arc, Mutex};

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let worker = Arc::clone(&state);
    tokio::spawn(async move {
        let guard = worker.lock().unwrap();
        let n = guard.len();
        tokio::task::yield_now().await;
        black_box(n)
    })
    .await
    .unwrap();
}
""",
    "std_drop": """
use std::hint::black_box;
use std::sync::{Arc, Mutex};

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let worker = Arc::clone(&state);
    tokio::spawn(async move {
        let guard = worker.lock().unwrap();
        let n = guard.len();
        drop(guard);
        tokio::task::yield_now().await;
        black_box(n)
    })
    .await
    .unwrap();
}
""",
    "std_scope": """
use std::hint::black_box;
use std::sync::{Arc, Mutex};

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let worker = Arc::clone(&state);
    tokio::spawn(async move {
        let n = {
            let guard = worker.lock().unwrap();
            guard.len()
        };
        tokio::task::yield_now().await;
        black_box(n)
    })
    .await
    .unwrap();
}
""",
    "parking_last_use": """
use parking_lot::Mutex;
use std::hint::black_box;
use std::sync::Arc;

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let worker = Arc::clone(&state);
    tokio::spawn(async move {
        let guard = worker.lock();
        let n = guard.len();
        tokio::task::yield_now().await;
        black_box(n)
    })
    .await
    .unwrap();
}
""",
}

# Preregistered by the frozen research protocol and confirmed on rustc 1.97.1.
EXPECTED_TO_COMPILE = {
    "std_last_use": False,
    "std_drop": False,
    "std_scope": True,
    "parking_last_use": False,
}


class SendProbeTests(unittest.TestCase):
    crate: Path
    temp: tempfile.TemporaryDirectory
    results: dict[str, tuple[int, str]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        require(cargo=True)
        cls.temp = tempfile.TemporaryDirectory()
        cls.copy = TempCrate(CASES, Path(cls.temp.name) / "cases")
        cls.crate = cls.copy.__enter__()
        binaries = cls.crate / "src" / "bin"
        binaries.mkdir(parents=True, exist_ok=True)
        for name, body in PROBES.items():
            path = binaries / f"{name}.rs"
            path.write_text(body.lstrip(), "utf-8")
            finished = run(["cargo", "check", "--quiet", "--bin", name], cls.crate, timeout=600)
            cls.results[name] = (finished.returncode, finished.stdout + finished.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "copy"):
            cls.copy.__exit__(None, None, None)
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def check(self, name: str) -> None:
        code, output = self.results[name]
        expected = EXPECTED_TO_COMPILE[name]
        self.assertEqual(
            code == 0, expected,
            f"{name}: expected compile={expected}, rustc said {code}\n{output[-1500:]}",
        )
        if not expected:
            self.assertIn(
                "Send", output,
                f"{name} was rejected, but not for the reason this probe is about",
            )

    def test_a_std_guard_alive_at_its_last_use_is_not_send(self):
        self.check("std_last_use")

    def test_dropping_a_std_guard_is_not_enough(self):
        """The behaviour the repair strategy depends on."""
        self.check("std_drop")

    def test_ending_the_lexical_scope_is_enough(self):
        self.check("std_scope")

    def test_a_parking_lot_guard_behaves_like_the_std_one(self):
        self.check("parking_last_use")

    def test_the_probes_disagree_with_the_folklore(self):
        """A summary assertion, so the point cannot be missed in a log.

        If `drop` ever becomes sufficient, this is the test that says so.
        """
        dropped = self.results["std_drop"][0] == 0
        scoped = self.results["std_scope"][0] == 0
        self.assertFalse(dropped, "drop(guard) unexpectedly satisfied Send")
        self.assertTrue(scoped, "a lexical scope unexpectedly failed to satisfy Send")


if __name__ == "__main__":
    unittest.main(verbosity=2)
