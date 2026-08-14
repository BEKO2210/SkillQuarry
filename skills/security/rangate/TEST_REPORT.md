# RanGate Test Report

## Status

RanGate 1.0.0 has been exercised as a packaged SkillQuarry skill on Linux, macOS arm64, stable Rust, optimized Rust, compile-fail doctests, and Miri. This report separates facts actually observed in CI from limits that remain external to the fixture.

## Reproduction

From `skills/security/rangate/`:

```bash
python3 tests/run_tests.py
```

The harness uses Python's standard library only. The Rust fixture has no `[dependencies]` or `[dev-dependencies]` sections.

Direct fixture commands:

```bash
cd tests/fixture
cargo fmt --check
cargo check --all-targets
RUSTFLAGS="-Dunsafe_op_in_unsafe_fn" cargo check --all-targets
cargo clippy --all-targets -- -D warnings
cargo test --all-targets -- --nocapture
cargo test --doc
cargo test --release --all-targets
cargo doc --no-deps
```

Miri CI command:

```bash
cargo +nightly-2026-08-13 miri setup
cargo +nightly-2026-08-13 miri test -- --nocapture
```

## Packaged-skill verification

GitHub Actions workflow: `.github/workflows/rangate-tests.yml`

Verification run: `31762243434`

The run tested the PR merge result for head commit `c982b4db335a45b422ce29b463733907b82589f6`. All three jobs completed successfully:

- `stable / ubuntu-24.04`
- `stable / macos-latest`
- `miri / nightly-2026-08-13`

### Linux environment

Observed in job `94650865969`:

- Ubuntu 24.04.4 LTS
- Git 2.54.0
- `rustc 1.97.1 (8bab26f4f 2026-07-14)`
- `cargo 1.97.1 (c980f4866 2026-06-30)`
- Python 3.12.3
- GNU Bash 5.2.21

Result:

```text
Ran 13 tests in 1.280s
OK
```

### macOS environment

Observed in job `94650866046`:

- macOS 26.5.2, build 25F84
- Git 2.55.0
- `rustc 1.97.1 (8bab26f4f 2026-07-14)`
- `cargo 1.97.1 (c980f4866 2026-06-30)`
- Python 3.14.6
- GNU Bash 3.2.57
- runner architecture: arm64 (`macos-26-arm64` image)

Result:

```text
Ran 13 tests in 4.292s
OK
```

This run includes the install → reinstall → uninstall test using a custom skills path containing spaces. The test also creates an unrelated `user-note.txt` and proves the uninstaller leaves it intact.

## Stable harness — 13 named checks

`tests/run_tests.py` verifies:

1. marketplace manifest contract;
2. `SKILL.md` frontmatter, four phases, output contract, and <=500-line ceiling;
3. reference docs and hand-written SVG assets, with no embedded raster image;
4. idempotent installer/uninstaller round trip and preservation of a user-added file;
5. dependency-free Edition 2024 Rust fixture and `unsafe_op_in_unsafe_fn = "deny"`;
6. `cargo fmt --check`;
7. `cargo check --all-targets`;
8. independent `RUSTFLAGS=-Dunsafe_op_in_unsafe_fn` compiler gate;
9. `cargo clippy --all-targets -- -D warnings`;
10. five runtime scenarios;
11. three compile-fail ownership/aliasing/thread proofs;
12. the five runtime scenarios again under `--release`;
13. `cargo doc --no-deps`.

## Five user-level scenarios

### 1. Beginner — raw knowledge disappears behind the safe API

Fixture test:

```text
beginner_safe_api_contains_raw_pointer_knowledge
```

A `Device` is constructed through the boundary, then read and mutated only through safe methods. The caller performs no raw-pointer dereference.

Result: PASS on Linux stable, macOS stable, release mode, and Miri.

### 2. Everyday — null-like foreign creation failure

Fixture test:

```text
null_like_foreign_failure_is_rejected_at_boundary
```

The simulated foreign API returns null for a sentinel input. `Device::open` converts that at the membrane into `DeviceError::AllocationRejected`; no invalid safe object is created and the allocation counter does not change.

Result: PASS on Linux stable, macOS stable, release mode, and Miri.

### 3. Advanced — panic while the raw resource is live

Fixture test:

```text
panic_unwinding_still_runs_raii_cleanup
```

The test intentionally panics while a `Device` exists, catches the unwind, and verifies the active-allocation counter returns to its pre-test value.

Result: PASS on Linux stable, macOS stable, release mode, and Miri.

### 4. Expert — the compiler must reject invalid safe programs

Command:

```bash
cargo test --doc
```

Three `compile_fail` examples are required to fail compilation for the intended architectural reasons:

- use after move / duplicate ownership: `E0382` observed;
- simultaneous mutable borrows: `E0499` observed;
- cross-thread transport with no proven foreign thread contract: `E0277` observed.

The Miri job also executed these doctests after the runtime suite. Result: 3 passed, 0 failed.

### 5. Adversarial — deterministic repetition plus optimizer

Fixture test:

```text
repeated_create_mutate_drop_cycles_do_not_leak
```

It performs 10,000 create → mutate → read → drop cycles and checks the actual fixture allocation counter returns to baseline. The same runtime suite is separately run through `cargo test --release --all-targets`.

Result: PASS on Linux stable, macOS stable, release mode, and Miri.

## Miri evidence

Observed in job `94650865921`:

- Ubuntu 24.04.4 LTS
- pinned toolchain: `nightly-2026-08-13`
- `rustc 1.99.0-nightly (c98d0cb27 2026-08-12)`
- `miri 0.1.0 (c98d0cb27c 2026-08-12)`

`cargo miri setup` completed successfully. It installed `rust-src` and constructed Miri's sysroot. That setup operation accessed Rust/crates infrastructure in CI; RanGate itself does not perform network access at runtime and does not install Miri for users.

The actual command `cargo +nightly-2026-08-13 miri test -- --nocapture` then executed the fixture:

```text
running 5 tests
...
test result: ok. 5 passed; 0 failed
```

The 10,000-cycle adversarial test ran under Miri, not merely under native Rust. The same Miri invocation then executed the three compile-fail doctests and reported 3 passed, 0 failed.

## Earlier prototype gate

Before packaging, isolated branch `test/rangate-pro-20260814` was used to decide whether the concept justified a full skill. GitHub Actions run `31761242014` used Rust 1.97.1 and already passed stable check, Clippy with warnings denied, five runtime tests, three compile-fail doctests, and release-mode tests.

The production fixture evolved from that prototype and was independently re-run in the packaged workflow above.

## Defects found during development

### D1 — the first prototype did not explicitly encode thread confinement

The earliest wrapper focused on null validation and unique ownership. That was insufficient for a foreign handle whose thread contract is unknown.

Fix: the production fixture includes a deliberate non-thread-safe marker plus a compile-fail `std::thread::spawn` example. The observed compiler diagnostic is `E0277`, so the test fails for the intended thread-transport reason.

### D2 — debug-only verification was too weak

The first small evaluation exercised debug behavior only.

Fix: the Pro matrix and production harness run the same runtime scenarios with `cargo test --release --all-targets`.

### D3 — explicit unsafe operations were initially a code-review convention, not an independent compiler gate

An `unsafe fn` can otherwise hide newly added unsafe operations inside its body on older edition assumptions.

Fix: the fixture sets `unsafe_op_in_unsafe_fn = "deny"`, includes `#![deny(unsafe_op_in_unsafe_fn)]`, and the harness independently repeats the check through `RUSTFLAGS=-Dunsafe_op_in_unsafe_fn`.

### D4 — the prototype test system duplicated the future production fixture

The exploratory branch left `experiments/rangate/` and `rangate-eval.yml` in the repository history. Keeping both would create two sources of truth.

Fix: the feature branch removes the prototype workflow/manifest and moves the evolved fixture under `skills/security/rangate/tests/fixture/`. The permanent workflow is `rangate-tests.yml`.

## Known limits

- The fixture simulates an FFI-like raw API in Rust. It proves the protocol can contain raw ownership and pointer invariants; it cannot prove that an arbitrary C/C++ library honors its external contract.
- Compile-fail doctests prove the three included invalid program shapes are rejected by the tested compiler. They are not a proof over every possible misuse.
- Miri detects important classes of undefined behavior in supported Rust execution, but it cannot establish undocumented semantics inside an arbitrary external foreign library.
- macOS was tested on an arm64 GitHub-hosted runner. Intel macOS was not tested.
- Linux was tested on x86_64 GitHub-hosted runners. Other Linux architectures were not tested.
- The Miri job intentionally uses network during CI toolchain/sysroot setup. RanGate's installed skill files have no runtime network requirement.
- RanGate is a protocol skill, not a whole-program static analyzer. Its result still depends on correctly identifying the real external ownership, lifetime, layout, and threading contract.
