---
name: rangate
description: Contain Rust unsafe, FFI, and raw-pointer invariants behind the smallest safe typed boundary. Use for unsafe refactors, FFI wrappers, raw ownership, pointer lifetimes, Send/Sync uncertainty, or reducing unsafe blast radius.
---

# RanGate

RanGate is a compiler-driven refactoring protocol for Rust `unsafe`, FFI, raw pointers, manual ownership, and low-level memory boundaries.

Its biological model is the nuclear pore complex: dangerous low-level representation stays on one side of a narrow boundary; only validated, typed capabilities cross into the safe domain. The goal is not to make `unsafe` disappear at any cost. The goal is to minimize how much code must understand its invariants.

Read [REFERENCE.md](REFERENCE.md) when you need the biological rationale, boundary patterns, or compiler-error interpretation table.

## Required tools

Use the repository's actual equivalents of:

- `read_file` / repository search
- `rust_analyzer` when available
- `cargo check`
- `cargo clippy`
- `cargo test`
- shell execution

Optional:

- `cargo miri test` when Miri is already available and the affected code is Miri-compatible
- `cargo doc`
- `git diff`

Do not install a new Rust toolchain, Miri, or third-party package without the user's explicit approval.

## Non-negotiable invariants

1. **Unsafe concentration** — unsafe knowledge moves toward fewer modules/functions, not outward into callers.
2. **No invariant leakage** — safe callers must not manually uphold pointer validity, alignment, initialization, aliasing, foreign ownership, or destruction rules.
3. **Convert at the boundary** — raw states become Rust types once: `NonNull`, `Option`, `Result`, enums, slices, RAII guards, newtypes, or typestate as appropriate.
4. **Local proof obligations** — every remaining unsafe block gets a concrete `SAFETY:` explanation tied to facts established by code, types, or a documented external contract.
5. **No invented contracts** — if an FFI lifetime, thread-safety, ownership, or layout guarantee is unknown, mark it `UNVERIFIED` and do not encode it as safe Rust.
6. **Compiler over confidence** — a model claim never overrides a failing compiler, test, lint, doctest, or Miri run.

# Phase 1 — Map the membrane

Do not refactor yet.

### 1. Establish the real verification baseline

Discover the workspace and its documented commands. Prefer the project's own CI/build commands when they differ from generic Cargo commands.

At minimum, when applicable, run:

```bash
cargo check --workspace
```

If the command fails before your change, record the exact baseline failure. Do not later claim that pre-existing failure was introduced or fixed unless you prove it.

### 2. Inventory unsafe surfaces

Search relevant Rust code for at least:

```text
unsafe
unsafe fn
*const
*mut
NonNull
MaybeUninit
UnsafeCell
transmute
from_raw
into_raw
get_unchecked
extern "C"
extern "system"
static mut
```

Classify each relevant occurrence:

```text
A  FFI boundary
B  raw allocation / ownership
C  pointer dereference
D  aliasing / interior mutability
E  layout / representation conversion
F  initialization
G  concurrency primitive
H  performance-only unsafe
I  unknown
```

For each actual unsafe operation, record:

```text
location:
category:
raw input:
raw output:
required invariant:
who currently proves it:
can a Rust type encode it:
```

### 3. Record the blast radius

Count or otherwise enumerate:

```text
unsafe blocks
unsafe functions
modules containing unsafe
public/raw pointer signatures
safe modules that know raw representation details
```

These are directional metrics, not a game. Never make code worse merely to reduce a count.

# Phase 2 — Build the pore

Choose the smallest module or type that can own the unsafe invariant.

Target dependency direction:

```text
external/raw representation
          ↓
private unsafe primitive
          ↓
validated boundary wrapper
          ↓
safe typed abstraction
          ↓
application/domain code
```

For every raw representation, ask in this order:

1. Can nullability become `Option<NonNull<T>>` or a constructor error?
2. Can ownership become a non-`Clone` RAII type with `Drop`?
3. Can state validity become an enum or typestate?
4. Can byte pointer + length become a slice with a proven lifetime?
5. Can integer status/discriminator values become a Rust enum or `Result`?
6. Can mutable aliasing be removed by ownership/borrowing?
7. Can the unsafe primitive become private?
8. Can thread movement remain forbidden unless the external contract proves it safe?

Never add `unsafe impl Send` or `unsafe impl Sync` merely to satisfy a compiler error. Require a concrete thread-safety contract first.

After the first boundary extraction, run the smallest useful compiler check immediately. Do not stack many speculative edits before asking the compiler.

# Phase 3 — Establish directionality with compiler feedback

Dangerous representation may flow:

```text
raw → validate once → safe typed capability
```

It must not leak back outward simply to make compilation easier.

After each meaningful refactor slice:

1. run `cargo check` for the smallest affected package/workspace scope;
2. interpret errors as invariant leaks before adding annotations or unsafe code;
3. repair the boundary;
4. repeat until the slice compiles;
5. then run the project's stronger lint/test gates.

Common signals:

```text
E0382          ownership transfer is not modeled correctly
E0499/E0502    mutation/aliasing boundary is still wrong
E0515          returned data outlives the owner/boundary
Send/Sync E0277
               thread transport lacks a proven contract or deliberate marker
lifetime error external lifetime assumptions are still implicit
visibility     boundary placement may be correct but API shape is incomplete
```

For Rust 2024-compatible code, require unsafe operations inside `unsafe fn` to remain inside explicit unsafe blocks. A useful independent check is:

```bash
RUSTFLAGS="-Dunsafe_op_in_unsafe_fn" cargo check --workspace
```

Do not suppress compiler or Clippy findings merely to get a green result.

# Phase 4 — Attack the membrane

Assume the refactor is wrong and try to prove it.

Test every applicable class:

### Null / invalid creation

Can a failed or null foreign handle enter the safe domain? Reject it at construction or encode absence explicitly.

### Double destruction / duplicate ownership

Can two safe values both believe they own the same raw resource? Prefer proving impossibility with move semantics or a compile-fail test.

### Use after move / release

Can safe code call the wrapper after ownership moved or the resource was destroyed? Add a compile-fail proof when practical.

### Mutable aliasing

Can two mutable safe paths reach the same underlying object? Make the compiler reject the shape before any unsafe operation is reached.

### Cross-thread movement

Inspect auto-traits. If the external API has no proven thread contract, keep the wrapper `!Send`/`!Sync` by construction rather than asserting an unsafe implementation.

### Panic / unwinding cleanup

If the wrapper owns a resource, force a panic while it is live and prove RAII cleanup still happens when the project's panic strategy permits unwinding.

### Repetition / resource exhaustion

Exercise repeated create/use/drop cycles at a deterministic high count. Check a real invariant such as an allocation counter, not elapsed time.

### Optimized build

Run relevant tests in release mode when unsafe behavior could be optimization-sensitive.

### Miri

If Miri is already installed and the code path is supported, run:

```bash
cargo miri test
```

Treat Miri as an additional dynamic checker, not a proof of all FFI contracts. If unavailable or incompatible, report that explicitly.

## Completion gate

Do not report `PASS` until all applicable independent gates you actually ran are green.

Compare the final unsafe blast radius with Phase 1. If a metric increased, explain precisely why the architecture is still safer. Never call an increase an improvement without evidence.

# Output format

Return exactly these sections.

## RANGATE_RESULT

```text
status: PASS | PARTIAL | BLOCKED

baseline:
  unsafe_blocks:
  unsafe_functions:
  modules_with_unsafe:
  raw_pointer_signatures:

final:
  unsafe_blocks:
  unsafe_functions:
  modules_with_unsafe:
  raw_pointer_signatures:
```

## MEMBRANE

```text
module:
responsibility:
unsafe_invariants_owned:
safe_abstraction_exposed:
```

## PROOF_OBLIGATIONS

For every remaining unsafe block:

```text
location:
operation:
required_invariant:
proof_in_code_or_type:
external_assumption:
```

Write `UNVERIFIED` for an external assumption you could not confirm.

## COMPILER_EVIDENCE

List only commands actually executed and their real results.

```text
cargo check ...: PASS | FAIL | NOT RUN
cargo clippy ...: PASS | FAIL | NOT RUN
cargo test ...: PASS | FAIL | NOT RUN
cargo test --doc ...: PASS | FAIL | NOT RUN
cargo miri test ...: PASS | FAIL | NOT RUN
```

## REFACTORED_CODE

Return complete changed Rust files when the calling environment expects code in the response. Do not use `...`, `rest unchanged`, or invented snippets as evidence.

## REMAINING_RISK

List only concrete remaining risks, for example:

```text
- upstream FFI lifetime guarantee is UNVERIFIED
- external library's thread-safety contract is undocumented
- Miri was not available
```

If none were identified, write:

```text
none identified
```

Never claim mathematical memory safety. RanGate's deliverable is a smaller, explicit, reviewable unsafe boundary backed by Rust's type system and compiler evidence.