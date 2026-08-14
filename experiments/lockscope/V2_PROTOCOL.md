# LockScope v2 Frozen Test Protocol

Date: 2026-08-14
Branch: `test/lockscope-v2-20260814`

## Purpose

Retest LockScope after replacing the production-critical regex acquisition/scope candidate layer with structured Rust syntax extraction.

The v2 detector under test MUST use:

1. `tree-sitter-rust` for committed-source `let` bindings, receiver/method structure, lexical blocks, await expressions, explicit `drop(...)`, and macro invocation locations;
2. rust-analyzer 1.97.1 for type/definition resolution and macro expansion;
3. compiler/runtime probes as independent ground truth;
4. the existing lock-order graph and conservative repair verifier.

The v2 semantic implementation must not call the v1 `base.ACQUIRE` or `base.MACRO_CALL` regex candidate scanners.

## Frozen toolchain

- Rust / Cargo / rust-analyzer: 1.97.1
- tree-sitter: 0.25.2
- tree-sitter-rust: 0.24.0
- CI semantic OSes: Ubuntu 24.04 and macOS latest

## Fixture gates

All inherited 20 semantic cases from the previous pro protocol remain required, including:

- Tokio Mutex, alias, owned guard;
- last textual use vs lexical scope;
- explicit drop and inner lexical scope;
- RwLock read/write distinction;
- std::sync and parking_lot;
- valid multiline Tokio acquisition;
- fake user `lock()` negative control;
- two-node, three-node and self lock-order cycles;
- consistent-order negative control;
- macro-generated Tokio acquisition.

### Corrected compiler ground truth

The previous experiment empirically disproved one expectation. v2 preregisters the observed Rust 1.97.1 truth rather than preserving the known-wrong expectation:

- `std_last_use`: must fail `tokio::spawn` Send bound;
- `std_drop`: must also fail Send bound;
- `std_scope`: must compile;
- `parking_last_use`: must fail Send bound.

This correction is made before the first v2 run and is not a post-hoc gate change.

### Five new structured-syntax cases

All 5/5 must pass:

1. multiline Tokio acquisition with an intervening comment;
2. parenthesized receiver `(state).lock().await`;
3. `Arc::clone(&state).lock_owned().await`;
4. nested lexical scope that must remain quiet after leaving the block;
5. multiline `std::sync::Mutex::lock().unwrap()` across await.

The structured candidate extractor must report exactly five supported acquisition bindings in the added v2 fixture file.

### Repair proof

The deterministic four-task Tokio contention proof remains unchanged:

- before: exclusive Tokio lock held while all tasks wait on a four-party barrier, deterministic timeout;
- repair: move acquisition behind the independent barrier await;
- after: finding cleared, all tasks finish, strict Clippy passes, no unsafe introduced.

### Determinism and runtime

- inherited fixture analysis must be deterministic;
- added v2 fixture analysis must be deterministic;
- Ubuntu and macOS must independently pass;
- full fixture v2 run must remain under 360 seconds per OS.

## Real repository gates

Exactly the same real-world oracles from v1 are retained:

### Javis

Before: `f0d6b556f459a3757b15e13fde3f5198b7d0826e`
After: `26f6e5db1d47af58e814809505929fa0c16ae1eb`

Required historical transition for `run_recall`:

- before includes `exclusive_lock_across_await`;
- after removes the exclusive finding and exposes the read-lock form;
- no invented cycle.

### Ferryman

Before: `8e9697b9eeee9db1e93a7e22eb7572650f5b001d`
After: `93b814fca8c6aca98e0f2a0859545b3ada4945a8`

Required transition:

- before detects exclusive lock across await in `mutate_job` and `claim_queued_job`;
- after clears both;
- no invented cycle.

### mini-redis

Pinned: `3d93b42bc363220f85af4fc9e1bebd35b588a4a3`

Required:

- healthy baseline cargo check/tests pass;
- healthy baseline has no lock-across-await finding/cycle;
- injected std MutexGuard across notified().await is detected;
- rustc independently rejects the injected spawned future as non-Send;
- conservative repair moves acquisition after the independent await;
- repaired cargo check/tests pass;
- finding clears;
- no unsafe introduced.

Baseline-red strict Clippy remains diagnostic-only exactly as in the previous frozen real-repository protocol; no regression may be attributed to the repair if baseline itself is red.

Real-repository runtime budget remains 720 seconds.

## Binding verdict

`PASS_V2` requires:

- Ubuntu fixture job PASS;
- macOS fixture job PASS;
- inherited 20/20 semantic cases;
- added structured 5/5 semantic cases;
- compiler Send probes 4/4 under corrected pre-run expectations;
- lock-order controls PASS;
- macro expansion case PASS;
- deterministic analyses PASS;
- Tokio repair PASS;
- Javis PASS;
- Ferryman PASS;
- mini-redis PASS;
- all runtime budgets PASS;
- no v1 regex candidate backend in `semantic_probe_v3.py`.

Any substantive miss is `FAIL_V2`. Only a demonstrable harness/infrastructure defect may be amended; any amendment must be documented without changing expected semantic cases, repository commits, repair tasks, or thresholds.
