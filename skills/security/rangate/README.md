<div align="center">

<img src="../../../assets/rangate-banner.svg" alt="RanGate — Rust unsafe and FFI boundary protocol" width="820">

<br>

**Unsafe stays behind the membrane. Safe Rust gets typed capabilities.**

[![Tests](https://img.shields.io/badge/tests-14%20passing-2ea043?style=for-the-badge)](TEST_REPORT.md)
[![Toolchain](https://img.shields.io/badge/rust-1.97.1%20pinned-2ea043?style=for-the-badge&logo=rust&logoColor=white)](TEST_REPORT.md)
[![Miri](https://img.shields.io/badge/miri-pinned%20nightly-5b8298?style=for-the-badge)](TEST_REPORT.md)
[![Dependencies](https://img.shields.io/badge/dependencies-none-3d5568?style=for-the-badge)](#install)
[![License](https://img.shields.io/badge/license-Apache--2.0-f0932b?style=for-the-badge)](../../../LICENSE)

[**Install**](#install) ·
[**Use**](#use) ·
[**How it works**](#how-it-works) ·
[**Safety posture**](#safety-posture) ·
[**Tests**](#tests) ·
[**Evidence**](TEST_REPORT.md)

</div>

---

## What it is

RanGate is a **protocol**, not a program: a set of instructions that makes a coding
agent refactor Rust `unsafe`, FFI, raw pointers and manual ownership the same way
every time, and prove the result with the compiler instead of asserting it.

Its model is the nuclear pore complex. Dangerous low-level representation stays on
one side of a narrow boundary; only validated, typed capabilities cross into the
safe domain. The goal is not to make `unsafe` disappear at any cost — it is to
shrink how much code has to understand its invariants.

A weak boundary leaks raw knowledge outward:

```text
application  ──raw pointer──▶  helper  ──raw pointer + safety note──▶  service  ──unsafe──▶  FFI
```

RanGate drives toward one crossing:

```text
foreign / raw domain
        │
        ▼   private unsafe primitive
        │
        ▼   validated ownership + lifetime boundary   ◀── the membrane
        │
        ▼   safe Rust capability
        │
        ▼   application code, which needs to know nothing
```

## Install

The skill is a document an agent reads; installing it means putting that document
where Claude Code looks for personal skills, `~/.claude/skills/<name>/SKILL.md`.

```bash
cd skills/security/rangate
./install.sh          # installs SKILL.md and REFERENCE.md
./uninstall.sh        # removes exactly those two files
```

`RANGATE_SKILLS_DIR=/somewhere/else ./install.sh` changes the target. The
installer writes atomically and leaves unrelated files in the target directory
untouched — there is a test for that.

Nothing else is installed. RanGate never adds a toolchain, a crate or a lint
configuration to your project.

## Use

From a Rust repository, in Claude Code:

```text
/rangate Refactor this FFI ownership boundary so callers no longer need
         raw-pointer knowledge. Prove the result with the compiler and tests.
```

**Use it when** the hard part is proving where dangerous invariants live: FFI
handles and `extern "C"`, `*const T` / `*mut T`, `NonNull<T>` wrappers,
`Box::into_raw` / `from_raw`, `MaybeUninit`, `UnsafeCell`, uncertain `Send`/`Sync`
boundaries, lifetimes dictated by foreign ownership, or unsafe knowledge that has
already spread into safe callers.

**Do not use it** as a general Rust review or as a replacement for `cargo clippy`.

## How it works

Four phases, in order. The full protocol is in [SKILL.md](SKILL.md); the
biological model and the compiler-error interpretation table are in
[REFERENCE.md](REFERENCE.md).

| Phase | What the agent does |
|---|---|
| 1 — Map the membrane | Establish a baseline that already passes, inventory every unsafe surface, record the blast radius as numbers |
| 2 — Build the pore | Move raw invariants into the smallest typed ownership and lifetime boundary |
| 3 — Establish directionality | Use compiler feedback to stop raw representation from leaking back outward |
| 4 — Attack the membrane | Challenge null handling, duplicate ownership, aliasing, thread movement, panic cleanup, repetition, optimized builds and Miri paths |

The agent reports through a fixed structure — `MEMBRANE`, `PROOF_OBLIGATIONS`,
`COMPILER_EVIDENCE`, `REFACTORED_CODE`, `REMAINING_RISK` — so a reviewer reads the
same sections every time, and anything unproven is marked `UNVERIFIED` rather than
quietly asserted.

## Safety posture

RanGate refuses the shortcuts that make a diff look safe without being safe:

- no invented FFI lifetime guarantees;
- no automatic `unsafe impl Send` or `Sync`;
- no `transmute` added to silence a type error;
- no lint suppression to turn CI green;
- no claim of mathematical memory safety;
- no claim that fewer `unsafe` blocks alone mean safer code.

Every remaining unsafe operation needs a local proof obligation tied to code,
types, or a real external contract.

## The fixture

`tests/fixture/` is a dependency-free crate simulating a small foreign resource
with a raw-pointer API. Its safe `Device` wrapper is what a finished RanGate
refactor should look like, and the suite proves it:

| Property | How it is proved |
|---|---|
| Null-like creation failure is rejected at the boundary | runtime test |
| Callers use a safe API after construction | runtime test |
| `Drop` releases exactly one raw allocation | allocation counter returns to baseline |
| Panic unwinding still runs RAII cleanup | runtime test |
| 10,000 create/mutate/read/drop cycles leak nothing | deterministic stress test |
| A moved owner cannot be used again | `compile_fail` proof, **E0382** |
| Two simultaneous mutable borrows are rejected | `compile_fail` proof, **E0499** |
| Cross-thread movement is rejected | `compile_fail` proof, **E0277** |

The three compile-fail proofs are checked by **reason**, not just by failure: each
snippet is compiled with `rustc --error-format=json` and must emit the pinned error
code. On stable, rustdoc ignores the code in the fence — a snippet with a typo, or
one annotated `E0999`, still counts as a pass, which would make the proof
worthless. See defect D5 in [TEST_REPORT.md](TEST_REPORT.md).

## Tests

```bash
python3 tests/run_tests.py
```

14 checks, standard library only, no packages and no toolchain installs. Checks
whose tool is missing skip with a message naming what to install; CI sets
`RANGATE_REQUIRE_TOOLCHAIN=1`, which turns the same condition into a failure so a
skip can never hide a broken skill.

Directly against the fixture:

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

**Miri** is additional dynamic evidence and is never installed automatically. CI
runs it on a pinned nightly, so stable users do not need nightly to use the skill:

```bash
cd tests/fixture && cargo miri test
```

A green Miri run is evidence about the fixture, not proof about the undocumented
semantics of an arbitrary C or C++ library.

## Evidence

Exact commands, toolchain versions, scenario mapping, the six documented defects
and the known limits: [TEST_REPORT.md](TEST_REPORT.md). The short independent
verification card a reviewer should work through:
[REVIEW.md](REVIEW.md). Sources behind the design: [REFERENCE.md](REFERENCE.md).

Apache-2.0, matching [SkillQuarry](../../../README.md).
