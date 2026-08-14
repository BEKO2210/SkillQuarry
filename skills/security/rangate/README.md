# RanGate

> **Unsafe stays behind the membrane. Safe Rust gets typed capabilities.**

RanGate is a compiler-driven SkillQuarry protocol for refactoring Rust `unsafe`, FFI, raw pointers, manual ownership, and low-level memory boundaries.

It is intentionally narrower than a generic Rust review skill. RanGate activates when the difficult part of the task is proving where dangerous invariants live and preventing those invariants from leaking through the rest of the codebase.

## What it changes

A weak boundary often looks like this:

```text
application
   ↓ raw pointer
helper
   ↓ raw pointer + caller safety note
service
   ↓ unsafe call
FFI
```

RanGate drives toward:

```text
foreign/raw domain
       ↓
private unsafe primitive
       ↓
validated ownership/lifetime boundary
       ↓
safe Rust capability
       ↓
application/domain code
```

The important result is not merely a lower `unsafe` count. The important result is that fewer modules need to know the raw validity, ownership, aliasing, lifetime, destruction, or threading contract.

## When to use it

Use RanGate for work involving:

- FFI handles and `extern "C"` / `extern "system"`
- `*const T` / `*mut T`
- `NonNull<T>` wrappers
- `Box::into_raw` / `Box::from_raw`
- manual initialization
- `MaybeUninit`
- `UnsafeCell`
- unsafe performance primitives
- uncertain `Send` / `Sync` boundaries
- lifetime problems caused by foreign ownership
- refactors where unsafe knowledge has spread into safe callers

Do not use it as a generic replacement for `cargo clippy` or ordinary idiomatic-Rust review.

## Install for Claude Code

Claude Code officially discovers personal skills from `~/.claude/skills/<skill-name>/SKILL.md`.

```bash
cd skills/security/rangate
./install.sh
```

Then start Claude Code in a Rust repository and invoke:

```text
/rangate Refactor this FFI ownership boundary so callers no longer need raw-pointer knowledge. Prove the result with the compiler and tests.
```

The installer accepts an alternate skills root for testing or custom setups:

```bash
RANGATE_SKILLS_DIR=/path/to/skills ./install.sh
```

Uninstall:

```bash
./uninstall.sh
```

## Protocol

The complete agent protocol is in [SKILL.md](SKILL.md).

The detailed systems-biology model and Rust boundary notes are in [REFERENCE.md](REFERENCE.md).

RanGate has four phases:

1. **Map the membrane** — establish baseline verification, inventory unsafe surfaces, and record blast-radius metrics.
2. **Build the pore** — move raw invariants into the smallest typed ownership/lifetime boundary.
3. **Establish directionality** — use compiler feedback loops to prevent raw representation from leaking back outward.
4. **Attack the membrane** — deliberately challenge null handling, duplicate ownership, aliasing, thread movement, panic cleanup, repetition, optimized builds, and Miri-compatible paths.

## Test fixture

`tests/fixture/` is a dependency-free Rust crate that simulates a small foreign resource with a raw pointer API. The safe `Device` wrapper demonstrates the exact properties RanGate is intended to create.

The fixture proves:

- null-like creation failure is rejected at the boundary;
- callers use a safe API after construction;
- `Drop` releases exactly one raw allocation;
- panic unwinding still executes RAII cleanup;
- 10,000 deterministic create/mutate/read/drop cycles return the allocation counter to baseline;
- a moved owner cannot be used again;
- two simultaneous mutable borrows are rejected;
- cross-thread movement is rejected while the external thread contract is deliberately unknown.

The last three are `compile_fail` doctests: the expected result is that Rust refuses to compile the invalid program.

## Reproduce the stable suite

From this directory:

```bash
python3 tests/run_tests.py
```

The harness uses only the Python standard library and the Rust tools already installed on the machine. It does not install packages or toolchains.

For the fixture directly:

```bash
cd tests/fixture
cargo fmt --check
cargo check --all-targets
RUSTFLAGS="-Dunsafe_op_in_unsafe_fn" cargo check --all-targets
cargo clippy --all-targets -- -D warnings
cargo test --all-targets -- --nocapture
cargo test --doc
cargo test --release --all-targets
```

## Miri

Miri is an additional dynamic checker for supported Rust code. RanGate never installs it automatically.

If Miri is already installed:

```bash
cd tests/fixture
cargo miri test
```

The SkillQuarry CI has a separate pinned-nightly Miri job so ordinary stable-toolchain users do not need nightly merely to use the skill.

A green Miri run is additional evidence, not proof of undocumented semantics in an arbitrary C or C++ library.

## Safety posture

RanGate deliberately refuses several common shortcuts:

- no invented FFI lifetime guarantees;
- no automatic `unsafe impl Send` or `Sync`;
- no `transmute` added just to silence type errors;
- no lint suppression merely to turn CI green;
- no claim of mathematical memory safety;
- no claim that fewer unsafe blocks alone means safer code.

Every remaining unsafe operation needs a local proof obligation tied to code, types, or an actual external contract.

## Test evidence

See [TEST_REPORT.md](TEST_REPORT.md) for exact commands, toolchain versions, scenario mapping, and known limits.

See [REVIEW.md](REVIEW.md) for the short independent verification card.

## License

Apache-2.0, matching SkillQuarry.