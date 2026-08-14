# LockScope

**Detect and repair dangerous Rust lock lifetimes — above all a lock held across
`.await`.**

```bash
cd skills/coding/lockscope && ./install.sh

lockscope scan .
lockscope repair . --json report.json
```

```text
verdict     FAIL
files       12
lock sites  9
findings    1
  critical sync_lock_across_await  src/db.rs:231 in purge_expired_tasks  (semantic)
```

## Why another lock checker

A `std::sync::MutexGuard` that is still alive at an `.await` blocks an executor
thread and usually makes the future non-`Send`. The compiler catches the second
half of that sentence only when the future is spawned; nothing catches the first
half. Meanwhile the obvious way to look for the problem — search for `.lock()` —
is wrong in both directions: it misses acquisitions written across several lines
or produced by a macro, and it flags every user-defined method that happens to
be spelled `lock`.

LockScope reads the code the way a compiler front end does and asks
rust-analyzer what each value actually is.

## How it works

```
Rust source
   │
   ├─ tree-sitter-rust ──── every `let` binding whose value chain ends in a
   │                        lock call: through .await, .unwrap(), ?, parentheses
   │
   ├─ rust-analyzer ─────── what is the method being called defined as?
   │                        what is the receiver? tokio / std / parking_lot —
   │                        or not a lock at all
   │
   ├─ lifetime ──────────── to the end of the block, or to drop(guard);
   │                        how many .await points fall inside that
   │
   ├─ lock-order graph ──── edges where one guard is live as another lock is
   │                        taken; cycles are the strongly connected components
   │
   ├─ repair ────────────── move the acquisition after the independent await,
   │                        or refuse and say why
   │
   └─ verification ──────── cargo check, cargo test, re-analysis, unsafe delta
```

Each step can only weaken the previous one's claim, never strengthen it: syntax
proposes, semantics confirms, the compiler decides.

## What it finds

| Finding | Severity | Meaning |
|---|---|---|
| `sync_lock_across_await` | critical | a blocking guard inside a future |
| `exclusive_lock_across_await` | high | every other task waits for a suspension it cannot influence |
| `read_lock_across_await` | medium | fine until a writer starves |
| `lock_order_cycle` | critical | two acquisition orders that can meet in the middle |
| `large_exclusive_critical_section` | advisory | a measurement, not a proof |

## The one repair it makes

```rust
// before                              // after
let mut guard = state.lock().await;    independent_work().await;
independent_work().await;              let mut guard = state.lock().await;
guard.push(value);                     guard.push(value);
```

It refuses to move an acquisition across a branch, a loop, or any use of the
guard, and says which one stopped it. Everything else — reordering locks,
splitting a critical section, changing a mutex type — is a design decision and
is reported as `MANUAL_REVIEW`.

**It never inserts `drop(guard)` in place of a scope.** On the pinned toolchain
that does not make a spawned future `Send`, while ending the lexical scope does.
The test suite compiles four probes to keep that claim tied to the compiler
rather than to folklore:

```text
std_last_use      expected non-Send  -> rustc rejected   PASS
std_drop          expected non-Send  -> rustc rejected   PASS
std_scope         expected Send      -> rustc accepted   PASS
parking_last_use  expected non-Send  -> rustc rejected   PASS
```

## Threat model

LockScope reads a repository, starts rust-analyzer and cargo inside it, and in
repair mode rewrites **one** source file by moving a single statement.

- **No network at runtime.** `install.sh` downloads the two pinned parser
  packages once, into a virtual environment that belongs to the installation.
- **No secrets.** Nothing is read from the environment except the install prefix.
- **Nothing outside the analysed repository is written**, other than a report
  file you name.
- **`unsafe` is never introduced.** The repair refuses to write a file that
  gained the keyword, and a test proves the refusal.
- **The analysed repository's build system runs.** `cargo check` and
  `cargo test` execute that project's code, including build scripts — the same
  exposure as building it by hand. Do not point `repair` at a repository you
  would not build.
- **A finding is not a proof of a bug, and no finding is not a proof of safety.**
  The limits are listed in SKILL.md and are not hidden here.

## Requirements

| | |
|---|---|
| Python | 3.10+, with `venv` |
| Rust | `cargo`, `rustc`, `rust-analyzer` |
| Parsers | `tree-sitter==0.25.2`, `tree-sitter-rust==0.24.0` (installed for you) |
| Platforms | Linux, macOS. Windows is untested and not claimed. |

`lockscope doctor` reports what is missing.

## Tests

```bash
python3 tests/run_tests.py                 # everything this machine can run
python3 tests/run_tests.py --structural    # no Rust toolchain needed
python3 tests/run_tests.py --real          # add the three pinned repositories
```

142 tests locally, plus 17 against pinned commits of three real repositories.
The numbers and the evidence are in [TEST_REPORT.md](TEST_REPORT.md); the
research this skill was promoted from is described in [RESEARCH.md](RESEARCH.md).
