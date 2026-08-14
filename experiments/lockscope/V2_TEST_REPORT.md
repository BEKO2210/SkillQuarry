# LockScope v2 Test Report

Date: 2026-08-14
Branch: `test/lockscope-v2-20260814`
Frozen protocol commit: `65e58908f3c0bd5e7475ac5e4696e3d77b11bb62`
CI amendment commit: `4353f0bfedf12018c28517c47090455d6327a602`
Passing workflow run: `31823072283`

## Binding verdict

**PASS_V2 — LockScope v2 passed the frozen production-strength evaluation.**

The v1 production blocker was removed by replacing regex-shaped lock acquisition/scope discovery with structured Rust syntax extraction (`tree-sitter-rust`) while retaining rust-analyzer for semantic type/definition resolution, compiler/runtime ground truth, lock-order analysis, and conservative repair verification.

This report does not merge anything into `main` and does not itself create a production SkillQuarry skill.

## Protocol integrity

The v2 acceptance protocol was committed before the first substantive run. It required:

- inherited 20/20 semantic cases;
- five additional structured-syntax cases;
- corrected Rust 1.97.1 Send ground truth fixed before the first v2 run;
- deterministic repeated analysis;
- Tokio contention repair proof;
- Ubuntu and macOS agreement;
- unchanged Javis, Ferryman, and mini-redis real-repository oracles;
- fixed runtime budgets;
- no use of v1 `base.ACQUIRE` or `base.MACRO_CALL` candidate scanners in `semantic_probe_v3.py`.

The first v2 workflow run (`31822890540`) encountered one infrastructure-only defect on macOS: Homebrew Python 3.14 rejected system-level pip installation under PEP 668 before any LockScope test executed. Amendment A1 moved the exact same pinned Python packages into a repository-local virtual environment. No semantic case, expectation, repository commit, repair task, or threshold changed.

## Toolchain

- rustc: `1.97.1 (8bab26f4f 2026-07-14)`
- cargo: `1.97.1`
- rust-analyzer: `1.97.1`
- tree-sitter: `0.25.2`
- tree-sitter-rust: `0.24.0`
- semantic CI: Ubuntu 24.04 and macOS 26 arm64 runner

## Ubuntu semantic result

Final verdict: `PASS_V2_FIXTURE`

```text
Inherited semantic cases:       20/20
Compiler Send probes:            4/4
Added AST cases:                 5/5
Structured candidate count:       5
Deterministic inherited:         PASS
Deterministic added cases:       PASS
Tokio contention repair:        PASS
No v1 regex candidate backend:  PASS
Total runtime:                39.933 s
Budget:                        <360 s
```

The exact v1 blocker now passes: the valid multiline Tokio acquisition is detected as `exclusive_lock_across_await` with one await while the guard is live.

## macOS semantic result

Final verdict: `PASS_V2_FIXTURE`

```text
Inherited semantic cases:       20/20
Compiler Send probes:            4/4
Added AST cases:                 5/5
Structured candidate count:       5
Deterministic inherited:         PASS
Deterministic added cases:       PASS
Tokio contention repair:        PASS
No v1 regex candidate backend:  PASS
Total runtime:                48.091 s
Budget:                        <360 s
```

Ubuntu and macOS therefore agree on all binding fixture gates.

## Corrected compiler ground truth

The v2 protocol preregistered the empirical Rust 1.97.1 behavior discovered by v1:

```text
std_last_use       expected non-Send -> compiler rejected -> PASS
std_drop           expected non-Send -> compiler rejected -> PASS
std_scope          expected Send     -> compiler accepted -> PASS
parking_last_use   expected non-Send -> compiler rejected -> PASS
```

This confirms that explicit `drop(std::sync::MutexGuard)` alone is not the same proof as ending the guard's lexical scope for the tested `tokio::spawn` Send requirement.

## Five new structured-syntax cases

All passed on Ubuntu and macOS:

1. multiline Tokio acquisition with an intervening comment -> detected;
2. parenthesized receiver `(state).lock().await` -> detected;
3. `Arc::clone(&state).lock_owned().await` -> detected;
4. nested lexical scope -> correctly quiet after scope exit;
5. multiline `std::sync::Mutex::lock().unwrap()` -> detected as sync lock across await.

The structured extractor reported exactly five supported acquisition bindings in the added fixture, as preregistered.

## Lock-order graph

The inherited lock-order cases remained correct. Detected cycles were exactly:

```text
self.a2 <-> self.b2
self.a3 -> self.b3 -> self.c3 -> self.a3
self.self_lock -> self.self_lock
```

The consistent-order control produced no false cycle.

## Macro case

The declarative macro-generated Tokio acquisition remained detectable through structured macro invocation discovery plus rust-analyzer expansion. The v2 engine emitted `exclusive_lock_across_await` for the generated guard on both operating systems.

## Tokio contention repair

The deterministic four-task repair proof remained green.

Before:

```rust
let mut guard = state.lock().await;
barrier.wait().await;
guard.push(1);
```

All tasks acquire the same mutex before reaching the four-party barrier, producing the expected timeout.

Repair:

```rust
barrier.wait().await;
let mut guard = state.lock().await;
guard.push(1);
```

Verified on Ubuntu and macOS:

- before finding detected;
- before behavior timed out;
- repair generated;
- finding cleared;
- all tasks completed;
- strict Clippy on the isolated repaired package passed;
- no `unsafe` introduced.

## Real repositories

Real-repository verdict: `PASS_REAL`
Runtime: **168.267 s** (< 720 s)

### Javis — PASS

Before: `f0d6b556f459a3757b15e13fde3f5198b7d0826e`
After: `26f6e5db1d47af58e814809505929fa0c16ae1eb`

LockScope v2 reproduced the historical transition in `run_recall`:

- before: `exclusive_lock_across_await` plus large exclusive critical section;
- after: exclusive finding cleared and `read_lock_across_await` remained visible;
- no cycle invented.

### Ferryman — PASS

Before: `8e9697b9eeee9db1e93a7e22eb7572650f5b001d`
After: `93b814fca8c6aca98e0f2a0859545b3ada4945a8`

Before, v2 detected `exclusive_lock_across_await` in both:

- `mutate_job`
- `claim_queued_job`

After, both findings cleared and no cycle was invented.

### mini-redis — PASS

Pinned commit: `3d93b42bc363220f85af4fc9e1bebd35b588a4a3`

Healthy baseline:

- `cargo check --locked`: PASS
- tests: PASS
- no lock-across-await finding: PASS
- no cycle: PASS

Injected fault:

```rust
let state = shared.state.lock().unwrap();
shared.background_task.notified().await;
if state.shutdown {
    break;
}
```

Independent and repair checks:

- v2 emitted `sync_lock_across_await`: PASS
- rustc rejected the spawned future as non-Send: PASS
- conservative repair generated: PASS
- lock acquisition moved after the independent await: PASS
- finding cleared: PASS
- repaired `cargo check --locked`: PASS
- repaired tests: PASS
- no unsafe introduced: PASS

Repaired shape:

```rust
shared.background_task.notified().await;
let state = shared.state.lock().unwrap();
if state.shutdown {
    break;
}
```

Strict Clippy on the pinned mini-redis baseline remained red for the pre-existing historical `useless_conversion`; the frozen baseline-relative rule therefore correctly prevented attributing that unrelated diagnostic to the repair.

## Final scorecard

```text
Ubuntu inherited semantic:       20/20
macOS inherited semantic:        20/20
Ubuntu added AST cases:            5/5
macOS added AST cases:             5/5
Compiler Send ground truth:        4/4
Lock-order expected cycles:        3/3
False cycle control:                 0
Macro-generated acquisition:      PASS
Deterministic analysis:            PASS
Tokio auto-repair:                 PASS
Javis historical oracle:           PASS
Ferryman historical oracle:        PASS
mini-redis negative + repair:      PASS
Fixture runtime budgets:           PASS
Real runtime budget:               PASS
v1 regex candidate backend used:     NO

Binding verdict:                PASS_V2
```

## Engineering conclusion

The reason v1 failed was correctly localized: its candidate/scope extraction was too text-shaped for production Rust syntax. Replacing that layer with a structured Rust syntax tree removed the known multiline failure without sacrificing alias handling, macro handling, cycle detection, compiler probes, deterministic behavior, or the real-repository results.

The experiment now supports a stronger conclusion than v1:

```text
LockScope concept:                VALIDATED
Structured v2 detector:           PASS_V2
Real repository evidence:         PASS_REAL
Conservative repair proof:        PASS
Promotion candidate:              YES
Automatic merge to main:          NO
Production skill creation:        separate next step
```

`PASS_V2` means the implementation passed this frozen evaluation. It is not a claim of complete Rust-language coverage or proof that every possible concurrency bug is detectable.
