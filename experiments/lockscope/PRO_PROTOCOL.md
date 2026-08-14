# LockScope Pro Test — preregistered protocol

Date: 2026-08-14
Branch: `test/lockscope-pro-20260814`
Status at commit time: rules frozen before the first pro workflow run.

## Question

Can a compiler-/rust-analyzer-backed LockScope protocol distinguish real Rust synchronization hazards from safe lock usage, recover historical lock-scope improvements in unrelated repositories, and produce conservative repairs that compile and preserve tests?

## Toolchain

- Rust `1.97.1`
- `rust-analyzer` component from the same toolchain
- `rust-src`
- Clippy from the same toolchain
- Python 3.12+

## Semantic fixture matrix

The fixture deliberately aliases lock types so names at the acquisition site cannot be trusted. Lock family is resolved from rust-analyzer hover/definition information.

Hard cases include:

1. Tokio Mutex guard held over await.
2. Tokio Mutex through a type alias.
3. Tokio `OwnedMutexGuard` via `lock_owned`.
4. Tokio guard with no textual use after the await (Drop-lifetime trap).
5. Explicit `drop(guard)` before await.
6. Inner lexical scope ending before await.
7. Tokio RwLock read guard over await.
8. Tokio RwLock write guard over await.
9. `std::sync::MutexGuard` over await.
10. std guard with last textual use before await.
11. explicit drop of std guard before await.
12. lexical scope around std guard.
13. parking_lot guard over await.
14. multiline acquisition syntax.
15. a custom user type whose method is literally named `lock` but is not a synchronization guard.
16. two-node field lock-order cycle.
17. three-node field lock-order cycle.
18. self-reacquisition of the same non-reentrant lock.
19. consistent global lock order (must not report a cycle).
20. simple macro-generated Tokio lock acquisition via rust-analyzer macro expansion.

The analyzer is run twice on the same fixture. Normalized results must be byte-for-byte deterministic.

## Compiler/runtime ground truth

Separate compiler/runtime probes decide Drop semantics rather than trusting the analyzer:

- Tokio guard with last textual use before an await is expected to keep the mutex unavailable until lexical scope exit.
- Explicit `drop(guard)` is expected to release it before the await.
- An inner lexical scope is expected to release it before the await.
- A Tokio RwLock read guard is expected to allow another reader while blocking a writer.
- A future containing a live `std::sync::MutexGuard` across await is expected to fail a `tokio::spawn` Send bound.
- The explicit-drop and lexical-scope std variants are expected to satisfy the Send bound.
- A live parking_lot guard across await is expected to fail the same Send bound under parking_lot's default guard policy.

If the compiler contradicts any preregistered expectation, that is a substantive result, not a harness error.

## Real repository historical oracles

### Javis

Repository: `BEKO2210/Javis`

- before: `f0d6b556f459a3757b15e13fde3f5198b7d0826e`
- after:  `26f6e5db1d47af58e814809505929fa0c16ae1eb`
- file: `crates/viz/src/state.rs`

Required transition:

- before `run_recall`: exclusive lock-across-await finding
- after `run_recall`: no exclusive lock-across-await finding; read-lock finding is allowed and should remain visible
- no invented lock-order cycle in either revision

`run_train` is allowed to remain exclusive; the historical change targeted read-only recall.

### Ferryman

Repository: `iMMIQ/ferryman`

- before: `8e9697b9eeee9db1e93a7e22eb7572650f5b001d`
- after:  `93b814fca8c6aca98e0f2a0859545b3ada4945a8`
- file: `src/bin/ferryman-web.rs`

Required transition:

- before `mutate_job`: exclusive lock-across-await
- after `mutate_job`: that finding disappears
- before `claim_queued_job`: exclusive lock-across-await
- after `claim_queued_job`: that finding disappears
- no invented lock-order cycle in either revision

### mini-redis

Repository: `tokio-rs/mini-redis`
Pinned commit: `3d93b42bc363220f85af4fc9e1bebd35b588a4a3`
File: `src/db.rs`

The healthy baseline must have no lock-across-await finding and no lock-order cycle. This is a real negative control: the file intentionally uses `std::sync::Mutex` only for short synchronous critical sections.

## Repair tests

### Real-repository repair

Inject into mini-redis's `purge_expired_tasks` a `std::sync::MutexGuard` that is acquired before `Notify::notified().await` and used after it.

Required behavior:

1. LockScope detects `sync_lock_across_await`.
2. `cargo check` rejects the mutation because the spawned future is not Send.
3. The conservative repair moves acquisition after the independent await; it must not add unsafe, sleeps, retries, or a new lock.
4. LockScope becomes quiet for that injected finding.
5. `cargo check` and `cargo test` pass after repair.
6. If baseline strict Clippy passes, repaired strict Clippy must also pass. If baseline strict Clippy is already red under Rust 1.97.1, that fact is recorded and Clippy is not used as a new failure invented by the repair.

### Tokio contention repair

A four-task fixture intentionally acquires a Tokio mutex before waiting at a four-party barrier. This deterministically prevents all four tasks from reaching the barrier.

Required behavior:

1. before repair: analyzer reports exclusive lock across await and program times out internally;
2. repair moves the independent barrier await before lock acquisition;
3. after repair: finding disappears, all four tasks complete, resulting vector length is four;
4. strict Clippy passes on the repaired binary.

## Acceptance gates

`PASS_PRO` requires all of the following:

- all 19 non-macro semantic fixture cases correct;
- the macro-generated case detected as well (20/20 total);
- zero false lock-order cycles in negative controls;
- two-node, three-node, and self-cycle cases detected;
- compiler/runtime Drop-semantic probes all match their preregistered outcomes;
- repeated fixture analysis is deterministic;
- Javis historical transition correct;
- Ferryman historical transition correct;
- mini-redis healthy baseline quiet;
- mini-redis injected failure detected and rejected by the compiler;
- mini-redis repaired state passes check/tests and the finding disappears;
- Tokio contention repair passes before/after behavioral proof;
- no repair introduces `unsafe`;
- semantic fixture job finishes within 5 minutes per OS;
- real-repository/repair job finishes within 12 minutes on Ubuntu.

Cross-platform requirement: the semantic fixture/ground-truth matrix must pass on both Ubuntu 24.04 and macOS latest.

Any missed hard case, false cycle, wrong historical transition, failed repair, or runtime-budget breach is `FAIL_PRO`.

## Allowed amendments

After the first workflow starts, only a demonstrated harness defect may be corrected (for example a wrong path, unavailable command, or fixture that fails before the intended property is exercised). The following may NOT be changed after observing results:

- expected classifications;
- historical commits;
- repair tasks;
- case count;
- acceptance thresholds;
- runtime budgets.

Every amendment must be recorded in the final report.