# LockScope

Find and conservatively repair dangerous Rust lock lifetimes — above all a lock
held across `.await` — using structured Rust syntax, rust-analyzer semantics,
compiler verification and lock-order analysis.

**The principle this skill serves**

> A lock should protect the smallest correct lexical region, and an asynchronous
> suspension should not happen while a dangerous guard is still live unless that
> lifetime is deliberate and justified.

## Use this skill when

- an async Rust function takes a lock and awaits before releasing it;
- `tokio::spawn` rejects a future with "cannot be sent between threads safely"
  and a guard is involved;
- a service stalls under load with tasks blocked on one mutex;
- two locks are taken in different orders in different places;
- you are reviewing async Rust that holds `Mutex`, `RwLock` or `parking_lot`
  guards;
- a critical section has grown large enough that nobody is sure what it covers.

## Do not use this skill for

- general Rust linting — that is Clippy's job, and LockScope does not replace it;
- proving a program deadlock-free — this is not a model checker;
- rewriting a working concurrency architecture because a report looks untidy;
- converting synchronous mutexes to async ones as a policy;
- inserting `drop(guard)` calls to silence findings;
- anything involving `unsafe`. LockScope never introduces it.

## What it needs

| Tool | Why |
|---|---|
| `rust-analyzer` | resolves what a value actually is; a method named `lock()` proves nothing |
| `cargo`, `rustc` | independent verification, and the ground truth about `Send` |
| `tree-sitter`, `tree-sitter-rust` | structured syntax; lock acquisitions are not a regular language |

`lockscope doctor` reports what is missing. Windows is not supported — it has
never been tested, and claiming it would be dishonest.

---

## Phase 1 — Map the lock topology

Before editing anything, run:

```bash
lockscope scan . --json lockscope-before.json
```

The scan does, in this order:

1. parses every `.rs` file into a syntax tree;
2. finds each `let` binding whose value chain ends in `lock`, `lock_owned`,
   `read`, `read_owned`, `write` or `write_owned` — through `.await`,
   `.unwrap()`, `?` and parentheses;
3. asks rust-analyzer what the *method* being called is defined as, then what
   the receiver is, and keeps the first answer that proves a lock family:
   - `tokio::sync::Mutex`, `tokio::sync::RwLock` → **async**
   - `std::sync::Mutex`, `std::sync::RwLock` → **sync**
   - `parking_lot` locks → **sync**
   - anything else → not a lock, and reported under `unresolved`;
4. expands macro invocations and reads any acquisition they generate;
5. measures each guard's lexical lifetime: to the end of its block, or to an
   explicit `drop(guard)`, whichever comes first;
6. counts the `.await` points that occur while the guard is live;
7. builds lock-order edges wherever one guard is still live as another lock is
   taken in the same function, and reports the cycles of that graph.

**Read the output before touching code.** In particular:

- `lock_sites[]` — every resolved acquisition, its guard, its family, its mode,
  where the guard dies, and how many awaits it spans;
- `unresolved[]` — bindings that looked like locks and were not proven to be
  any; a real lock that lands here means the workspace did not resolve, not
  that the code is safe;
- `cycles[]` — acquisition orders that form a ring.

## Phase 2 — Classify the risk

| Finding | Severity | Why |
|---|---|---|
| `sync_lock_across_await` | critical | a blocking guard in a future: it blocks the executor thread and usually makes the future non-`Send` |
| `exclusive_lock_across_await` | high | correct but serialising: every other task waits for a suspension it cannot influence |
| `read_lock_across_await` | medium | tolerable under low contention; dangerous where a writer can starve |
| `lock_order_cycle` | critical | two orders that can meet in the middle |
| `large_exclusive_critical_section` | advisory, or high with an await | a measurement, not a proof |

Each finding carries a `confidence`, and it is not decoration:

- `compiler` — the compiler said so;
- `semantic` — rust-analyzer resolved the type;
- `graph` — derived from acquisition order;
- `heuristic` — a threshold was crossed. Judgement required.

Never raise or lower a severity because of how the code looks. A guard whose
lifetime is deliberate — a critical section that genuinely must span the await —
is documented, not silently repaired.

## Phase 3 — Design the smallest safe repair

Preferred, in order:

**1. Take the lock after the independent work.** The only repair LockScope
applies by itself.

```rust
// before
let mut guard = state.lock().await;
independent_async_work().await;
guard.push(value);

// after
independent_async_work().await;
let mut guard = state.lock().await;
guard.push(value);
```

**2. End the guard's lexical scope before the await.**

```rust
let result = {
    let guard = state.lock().await;
    compute_from_guard(&guard)
};
independent_async_work(result).await;
```

**3. Copy out what is needed, then release.** Where the guarded data is small
and cheap to clone.

### Forbidden repairs

- **`drop(guard)` as a substitute for scope.** On the pinned toolchain, an
  explicit `drop` of a `std::sync::MutexGuard` does *not* make a spawned future
  `Send`; ending the lexical scope does. The compiler probes in this skill's
  test suite record that behaviour, and they will fail loudly if a future
  release changes it. Never treat a textual `drop()` as proof.
- **Moving an acquisition across a branch, a loop, or a use of the guard.** The
  tool refuses; so should you.
- **Reordering two locks to break a cycle** without proving the invariant that
  made the original order necessary. Ambiguous ordering is `MANUAL_REVIEW`.
- **Splitting an atomic critical section** so a detector goes quiet. If two
  updates must be seen together, they must stay together.
- **Swapping `std::sync::Mutex` for `tokio::sync::Mutex`** to silence a finding.
  That changes fairness, performance and cancellation behaviour, and is an
  architectural decision.
- **Introducing `unsafe`.** Never, for any finding.

## Phase 4 — Verify independently

```bash
lockscope repair . --json lockscope-after.json
```

The repair runs its own verification and reports it. A repair only stands when
all of these hold:

- `cargo check --all-targets` passes;
- `cargo test` passes;
- the re-analysis no longer reports the finding;
- the unsafe count is unchanged;
- the file still parses.

Add, by hand, whatever the change deserves:

- `cargo clippy --all-targets -- -D warnings`, compared against the **baseline
  before the change**. A repository that was already red stays red without that
  counting against the repair;
- the runtime reproduction that showed the problem, run again;
- `git diff`, read line by line. The supported repair moves exactly one
  statement; a larger diff means something else happened.

The verifier can reject the repair. When it does, revert and treat the finding
as `MANUAL_REVIEW`.

## Output

`lockscope scan --json -` writes one stable envelope:

```json
{
  "schema": "lockscope.report/1",
  "toolchain": {"rustc": "...", "cargo": "...", "rust_analyzer": "...",
                "tree_sitter": "...", "tree_sitter_rust": "..."},
  "files_analyzed": 12,
  "lock_sites": [
    {"file": "src/db.rs", "function": "purge_expired_tasks", "line": 231,
     "guard": "state", "lock_expr": "shared.state", "family": "sync",
     "mode": "exclusive", "origin": "source", "awaits_while_live": 1,
     "scope_end_line": 248, "explicit_drop_line": null, "span_lines": 17}
  ],
  "cycles": [["self.accounts", "self.sessions"]],
  "findings": [
    {"kind": "sync_lock_across_await", "severity": "critical",
     "confidence": "semantic", "file": "src/db.rs", "line": 231,
     "evidence": "sync exclusive guard `state` is live across 1 await point(s)"}
  ],
  "repairs": [], "refusals": [], "verification": {}, "unresolved": [],
  "timings": {"total_seconds": 12.4}, "verdict": "FAIL"
}
```

Ordering is deterministic: the same code produces byte-identical output, so two
reports can be diffed and a re-analysis after a repair means something.

**Verdicts.** `PASS` — nothing dangerous was proven. `FAIL` — a lock is held
across an await. `MANUAL_REVIEW` — something real was found that this skill will
not repair on its own, such as a lock-order cycle.

**Exit codes.** `0` pass · `1` findings · `2` manual review · `3` the analysis
could not run. A `3` is never a statement about the code.

## Stop conditions

Stop and report instead of continuing when:

- rust-analyzer cannot resolve the workspace — every finding would be a guess;
- a candidate that is obviously a lock appears under `unresolved`;
- the repair verification fails;
- a cycle is reported: ordering is a design decision;
- the guard is held deliberately and the code says so.

## Escalate to a human when

- the critical section must span the await for correctness;
- breaking a cycle requires choosing a global lock order;
- the fix is architectural — sharding a lock, moving to message passing,
  replacing a mutex with an actor;
- the repository's own tests do not cover the path being changed.

## What LockScope does not see

Stated plainly, because a tool that hides its limits cannot be trusted with the
ones it claims:

- **Guards that are never bound.** `if let Some(v) = *m.lock().await` holds a
  temporary; its lifetime is not modelled.
- **Guards moved into another owner** — stored in a struct, sent to another
  function, captured and returned.
- **Procedural macros** whose expansion rust-analyzer cannot produce.
- **Deadlock freedom.** A cycle is evidence of risk, not a proof of failure —
  and no cycle is not a proof of safety.
- **Runtime contention** that no lexical analysis can predict.
- **Windows.** Untested.
