# LockScope Pro Test Report

Date: 2026-08-14
Branch: `test/lockscope-pro-20260814`

## Binding verdict

**FAIL_PRO — do not promote the current LockScope implementation as a production SkillQuarry skill.**

This is not a rejection of the LockScope problem or repair strategy. The real-repository and repair portions passed. The failure is specifically that the preregistered production-strength semantic detector did not satisfy all syntax/compiler ground-truth gates.

## Frozen protocol

The acceptance rules were committed before the first workflow run in `PRO_PROTOCOL.md` at commit:

`abf66c29fe62a65e06ce6f0697538553f43533b6`

The protocol required, among other gates:

- 20/20 semantic fixture cases;
- compiler/runtime Drop and Send ground truth;
- deterministic repeated analysis;
- correct historical transitions in Javis and Ferryman;
- a quiet healthy mini-redis control;
- a real mini-redis injected failure detected, compiler-rejected, and repaired;
- a deterministic Tokio contention repair;
- Ubuntu + macOS semantic agreement;
- fixed runtime budgets.

Any missed hard case was preregistered as `FAIL_PRO`.

## Run 1

Workflow: `31817638259`
Commit: `abf66c29fe62a65e06ce6f0697538553f43533b6`

Run 1 exposed two harness defects and one substantive compiler counterexample.

### Harness defect A1 — semantic family evidence

Tokio sites were not classified because family detection relied too heavily on guard hover text and a registry-path pattern that did not match real versioned Tokio paths. The std::sync mini-redis injection *was* detected, showing the LSP/parser path itself was active.

Allowed amendment:

- add method hover and receiver `typeDefinition` evidence;
- recognize versioned Tokio/parking_lot/lock_api paths;
- treat syntactic acquisitions + zero semantic classifications as analyzer failure rather than a clean result.

### Harness defect A2 — repair Clippy isolation

Strict Clippy for the Tokio repair binary also linted the intentionally hazardous ground-truth library in the same package. The exact repair scenario was moved to a standalone tiny Cargo package so strict Clippy measured only the repaired program.

Neither amendment changed expected cases, repositories, commits, repair task, case count, thresholds, or runtime budgets. They are documented in `PRO_AMENDMENTS.md`.

### Substantive counterexample — explicit `drop` is not enough for Send

The preregistration expected this shape to satisfy `tokio::spawn`'s `Send` bound:

```rust
let guard = state.lock().unwrap();
let n = guard.len();
drop(guard);
tokio::task::yield_now().await;
black_box(n)
```

On Rust 1.97.1, both Ubuntu and macOS rejected it: the async block still contains a `std::sync::MutexGuard` across a suspension point for generator/Send analysis.

The lexical-scope form compiled:

```rust
let n = {
    let guard = state.lock().unwrap();
    guard.len()
};
tokio::task::yield_now().await;
black_box(n)
```

This is a binding failed preregistered expectation. The amended run therefore could not turn the original experiment into `PASS_PRO`.

It also corrects the small-test model: "last textual use" is not a safe substitute for a guard's lexical/drop lifetime.

## Amended run 2

Workflow: `31818094089`
Commit: `318da4fae5c00d217be5717ce1f2c3454e0b989e`

### Semantic fixture — Ubuntu

- semantic cases: **19/20**
- deterministic repeat: **PASS**
- compiler Send probes: **3/4**
- Tokio contention repair: **PASS**
- runtime: **32.479 s** (< 300 s)
- verdict: `FAIL_FIXTURE`

### Semantic fixture — macOS

- semantic cases: **19/20**
- deterministic repeat: **PASS**
- compiler Send probes: **3/4**
- Tokio contention repair: **PASS**
- runtime: **55.351 s** (< 300 s)
- verdict: `FAIL_FIXTURE`

Both operating systems reproduced the same two failures.

### Semantic miss — multiline acquisition

The only 20-case semantic miss was valid multiline Rust:

```rust
let mut guard = state
    .lock()
    .await;
tokio::task::yield_now().await;
guard.push(1);
```

LockScope resolved the site as a Tokio mutex but computed zero awaits while the guard was live, so it failed to emit `exclusive_lock_across_await`.

This is a real detector limitation under the preregistered case, not an infrastructure failure.

The normalized output also showed another reason not to promote the parser: nested lexical-scope examples could be syntactically associated with the outer binding (`guard: "n"`, lock expression resembling `{letguard=state`). They happened not to cause a wrong expected finding in this matrix, but they demonstrate that regex candidate extraction remains structurally fragile.

### What the semantic engine did correctly

Across both operating systems it correctly handled:

- Tokio Mutex;
- Tokio Mutex type alias;
- Tokio `OwnedMutexGuard` / `lock_owned`;
- Tokio last-use-vs-scope lifetime trap;
- explicit Tokio drop;
- lexical-scope Tokio drop;
- RwLock read vs write distinction;
- std::sync MutexGuard;
- parking_lot MutexGuard;
- fake user type with a method named `lock` (ignored);
- declarative macro-generated Tokio acquisition via rust-analyzer expansion;
- two-node lock-order cycle;
- three-node lock-order cycle;
- self-reacquisition cycle;
- consistent lock order without false cycle.

Detected cycles were exactly:

```text
self.a2 <-> self.b2
self.a3 -> self.b3 -> self.c3 -> self.a3
self.self_lock -> self.self_lock
```

No cycle was invented for the consistent-order control.

## Tokio contention repair

The controlled repair proof passed on Ubuntu and macOS.

Before:

```rust
let mut guard = state.lock().await;
barrier.wait().await;
guard.push(1);
```

Four tasks each took the mutex before reaching a four-party barrier, so the program deterministically timed out.

The conservative repair moved acquisition after the independent barrier await:

```rust
barrier.wait().await;
let mut guard = state.lock().await;
guard.push(1);
```

Results:

- before finding detected: PASS
- before behavioral timeout: PASS
- repair generated: PASS
- finding cleared: PASS
- all four tasks completed: PASS
- strict Clippy on repaired standalone package: PASS
- no `unsafe`: PASS

## Real repositories — PASS_REAL

The amended real-repository job completed in **158.229 s**, below the frozen 720-second limit.

### Javis historical transition — PASS

Repository: `BEKO2210/Javis`

Before:
`f0d6b556f459a3757b15e13fde3f5198b7d0826e`

After:
`26f6e5db1d47af58e814809505929fa0c16ae1eb`

LockScope correctly reported before `run_recall`:

- `exclusive_lock_across_await`
- `large_exclusive_critical_section`

After the historical concurrency refactor it correctly removed the exclusive finding and retained:

- `read_lock_across_await`

No lock-order cycle was invented in either revision.

This is the historically measured Javis refactor that changed recall from a global Mutex-serialized path to read-only state/RwLock and reported roughly a 2.5x throughput improvement.

### Ferryman historical transition — PASS

Repository: `iMMIQ/ferryman`

Before:
`8e9697b9eeee9db1e93a7e22eb7572650f5b001d`

After:
`93b814fca8c6aca98e0f2a0859545b3ada4945a8`

Before, LockScope detected `exclusive_lock_across_await` in both:

- `mutate_job`
- `claim_queued_job`

After the historical refactor, both findings disappeared. No cycle was invented.

### mini-redis real negative + injected repair — PASS

Repository: `tokio-rs/mini-redis`
Pinned commit:
`3d93b42bc363220f85af4fc9e1bebd35b588a4a3`

Healthy baseline:

- cargo check: PASS
- cargo tests: PASS
- no lock-across-await finding: PASS
- no lock-order cycle: PASS

Baseline strict Clippy was already red under Rust 1.97.1 for an unrelated historical `useless_conversion`, so the preregistered baseline-red rule correctly prevented attributing that failure to the repair.

Injected into `purge_expired_tasks`:

```rust
let state = shared.state.lock().unwrap();
shared.background_task.notified().await;
if state.shutdown {
    break;
}
```

Results:

- LockScope emitted `sync_lock_across_await`: PASS
- rustc rejected the spawned future as non-Send: PASS
- conservative repair moved the acquisition after the independent await: PASS
- finding cleared: PASS
- repaired cargo check: PASS
- repaired cargo tests: PASS
- no unsafe introduced: PASS

Final repaired shape:

```rust
shared.background_task.notified().await;
let state = shared.state.lock().unwrap();
if state.shutdown {
    break;
}
```

## Final scorecard

```text
Semantic hard cases, Ubuntu:     19/20
Semantic hard cases, macOS:      19/20
Compiler Send ground truth:       3/4
Deterministic analysis:           PASS
Lock-order cycles:                3/3
False cycle in control:           0
Macro-generated acquisition:      PASS
Tokio contention auto-repair:     PASS
Javis historical oracle:          PASS
Ferryman historical oracle:       PASS
mini-redis healthy negative:      PASS
mini-redis real auto-repair:      PASS
Runtime budgets:                  PASS

Binding protocol verdict:         FAIL_PRO
Real-repository sub-verdict:      PASS_REAL
```

## Engineering conclusion

LockScope's **problem definition and conservative repair idea are validated enough to keep**. It found two unrelated historical real-world concurrency transitions and repaired a compiler-proven mini-redis fault. The lock-order graph also behaved well in the hard fixture.

The current **detector implementation is not production-ready** because its syntax candidate layer is still regex-shaped. Valid multiline acquisition already escaped the await-lifetime calculation, and nested bindings exposed misassociation artifacts.

The next LockScope version should replace regex candidate extraction with structured Rust syntax/HIR acquisition ranges while retaining rust-analyzer type/definition resolution, the lock-order graph, compiler Send probes, and the conservative repair verifier.

Production decision:

```text
LockScope concept:              KEEP
Small test:                     PASS_SMALL
Real repository sub-test:       PASS_REAL
Frozen full pro protocol:       FAIL_PRO
Current parser promotion:       NO
SkillQuarry production merge:   NO
Next action:                    rewrite syntax extraction, then retest
```

No production skill or main-branch merge is justified by this pro test.