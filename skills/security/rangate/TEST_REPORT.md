# RanGate Test Report

## Status

This report distinguishes the already completed prototype evaluation from the final packaged-skill verification. No result is claimed without a reproducible command or a GitHub Actions run.

## Previously completed prototype evaluation

An isolated branch (`test/rangate-pro-20260814`) was used before packaging the skill.

GitHub Actions run: `31761242014`

Environment recorded by the run:

- Ubuntu 24.04.4 LTS
- `rustc 1.97.1 (8bab26f4f 2026-07-14)`
- `cargo 1.97.1 (c980f4866 2026-06-30)`
- Git 2.54.0

The run completed successfully with:

- `cargo fmt --check`
- `cargo check --all-targets`
- `RUSTFLAGS=-Dunsafe_op_in_unsafe_fn cargo check --all-targets`
- `cargo clippy --all-targets -- -D warnings`
- five runtime tests: 5 passed, 0 failed
- three compile-fail doctests: 3 passed, 0 failed
- release-mode runtime tests: 5 passed, 0 failed

The packaged skill contains the evolved form of that fixture under `tests/fixture/`; the production workflow must still independently re-run it.

## Stable packaged-skill suite

Reproduction command from `skills/security/rangate/`:

```bash
python3 tests/run_tests.py
```

The harness contains 13 named tests covering:

1. manifest contract;
2. SKILL frontmatter, required phases/output, and the 500-line ceiling;
3. documentation and hand-written SVG asset presence;
4. idempotent installer/uninstaller round trip in a path containing spaces, including preservation of a user-created extra file;
5. dependency-free Rust fixture contract;
6. rustfmt;
7. cargo check;
8. explicit unsafe-operation lint;
9. Clippy with warnings denied;
10. five runtime scenarios;
11. three compile-fail ownership/aliasing/thread proofs;
12. optimized release-mode scenarios;
13. rustdoc build.

Final packaged-skill CI run ID and output are filled in only after the branch workflow has completed.

## Five user-level scenarios

### 1. Beginner — safe wrapper hides raw-pointer knowledge

Fixture test:

```text
beginner_safe_api_contains_raw_pointer_knowledge
```

Expected property: after `Device::open`, the caller uses safe `get`/`set` methods and performs no raw dereference.

### 2. Everyday — foreign creation failure rejected at the membrane

Fixture test:

```text
null_like_foreign_failure_is_rejected_at_boundary
```

Expected property: the simulated foreign API returns null for a sentinel input, and no invalid `Device` enters the safe domain.

### 3. Advanced — panic during a live foreign resource

Fixture test:

```text
panic_unwinding_still_runs_raii_cleanup
```

Expected property: after an intentional panic is caught, the active-allocation counter has returned to its pre-test value.

### 4. Expert — invalid safe programs must fail to compile

Doctest command:

```bash
cargo test --doc
```

Three `compile_fail` programs assert that Rust rejects:

- use after move / duplicate ownership;
- two simultaneous mutable borrows;
- moving the wrapper to another thread while its external thread contract is unknown.

### 5. Adversarial — deterministic repetition and optimized build

Fixture test:

```text
repeated_create_mutate_drop_cycles_do_not_leak
```

It performs 10,000 create → mutate → read → drop cycles and checks the real allocation counter returns to baseline. The same runtime suite is also executed with `cargo test --release --all-targets`.

## Miri

The permanent workflow contains a separate pinned-nightly Miri job. A Miri result is not recorded here until that exact packaged-skill job has executed.

Official Miri usage reference:

- https://github.com/rust-lang/miri

## Defects found during development

### D1 — first prototype did not prove thread confinement

The initial simple wrapper used only `NonNull<T>`. That tested ownership and null handling but did not encode the deliberate policy that a foreign handle with an unknown thread contract must not cross threads.

Fix: the Pro fixture adds a zero-sized `PhantomData<Rc<()>>`, making the wrapper deliberately `!Send`/`!Sync`, plus a compile-fail doctest that verifies `std::thread::spawn` rejects it.

### D2 — the first prototype only checked debug behavior

An unsafe boundary that passes debug tests alone leaves optimizer-sensitive behavior untested.

Fix: the Pro matrix runs the same runtime scenarios with `cargo test --release --all-targets`.

### D3 — implicit unsafe operations inside `unsafe fn` were not an independent gate

Merely seeing explicit blocks in source was not a compiler-enforced regression guard.

Fix: the fixture denies `unsafe_op_in_unsafe_fn`, and the harness additionally runs Cargo with `RUSTFLAGS=-Dunsafe_op_in_unsafe_fn`.

## Known limits

- The fixture simulates an FFI-like API in Rust. It proves the protocol can contain raw ownership and pointer operations, not that any arbitrary C/C++ library obeys its documented contract.
- Compile-fail doctests prove those example invalid programs are rejected by the tested compiler; they are not a general proof over all possible misuse.
- Miri cannot validate undocumented semantics inside an arbitrary external foreign library.
- Linux CI is mandatory. macOS compatibility of the shell installer is targeted but must be checked by the workflow matrix before being claimed.
- RanGate is a protocol skill, not a Rust static analyzer. Its quality depends on the agent accurately mapping the real external contract and on independent compiler/test evidence.
