# RanGate Reference

RanGate translates a specific systems-biology pattern into a Rust refactoring discipline: the nuclear pore complex separates two domains with different rules and permits controlled transport through a narrow, selective boundary.

## Biological model

Eukaryotic cells keep the nucleoplasm and cytoplasm chemically distinct while still exchanging proteins and RNA through nuclear pore complexes (NPCs). NPC selectivity is strongly associated with FG-repeat nucleoporins; transport receptors bind cargo and interact with this selective environment. Directionality for many transport cycles depends on the Ran GTPase system, whose asymmetric nucleotide state across the nuclear envelope biases cargo loading and release.

RanGate does not claim that Rust ownership is biologically identical to nuclear transport. The useful abstraction is architectural:

1. two domains have different admissible representations;
2. crossing happens through a small number of controlled gates;
3. cargo is transformed/validated at the gate;
4. directionality prevents low-level representation from diffusing back into the high-level domain.

Primary literature and reviews worth checking when changing this model:

- Görlich D, Kutay U. Transport between the cell nucleus and the cytoplasm. *Annual Review of Cell and Developmental Biology* 1999;15:607-660. DOI: 10.1146/annurev.cellbio.15.1.607
- Frey S, Görlich D. A saturated FG-repeat hydrogel can reproduce the permeability properties of nuclear pore complexes. *Cell* 2007;130(3):512-523. DOI: 10.1016/j.cell.2007.06.024
- Schmidt HB, Görlich D. Transport selectivity of nuclear pores, phase separation, and membraneless organelles. *Trends in Biochemical Sciences* 2016;41(1):46-61. DOI: 10.1016/j.tibs.2015.11.001

## Rust translation

### Raw domain

Examples:

- `*mut T` / `*const T`
- foreign handles
- pointer-plus-length pairs
- integer discriminators
- manually initialized memory
- C ownership conventions
- external thread-safety contracts

These representations are not automatically wrong. They are expensive because their validity is carried by facts outside Rust's ordinary type system.

### Pore

The pore is the smallest code region that must understand those facts.

Typical tools:

- `NonNull<T>` for validated non-null pointers
- `Drop` for unique destruction ownership
- a non-`Clone` owner type for single ownership
- `Option` / `Result` for absent or failed creation
- slices after pointer+length validation
- enums/newtypes for discriminators
- typestate for lifecycle transitions
- `PhantomData` when ownership/lifetime/auto-trait semantics must be represented without stored Rust references

### Safe domain

Application code should receive ordinary Rust semantics: borrowing, ownership, enums, `Result`, slices, guards, or domain objects. It should not repeatedly reconstruct raw preconditions.

## Boundary rules

### Nullability

A raw pointer that may be null should normally be converted at the boundary, for example with `NonNull::new`. Do not allow every caller to remember a null check.

### Ownership

If a foreign resource has exactly one destroy operation, represent that fact with a unique owner and `Drop` when the contract permits it. Do not derive `Clone` for unique foreign ownership merely for convenience.

### Borrowing

A wrapper does not magically prove a foreign aliasing contract. Returning `&T` or `&mut T` from foreign memory requires the same lifetime and aliasing justification as creating those references anywhere else.

### Send and Sync

Raw pointers and wrapper fields interact with Rust auto-trait derivation, but auto-trait behavior is not a substitute for the foreign library's concurrency contract. Do not write `unsafe impl Send` or `unsafe impl Sync` until the external guarantees are known and documented.

One conservative technique for a handle whose thread contract is unknown is to make it deliberately non-`Send`/non-`Sync` by construction, then relax that only when evidence exists.

### Unsafe functions

An `unsafe fn` means callers must satisfy additional safety obligations. It should not turn the entire body into an implicit free-fire zone. Rust's `unsafe_op_in_unsafe_fn` lint exists specifically to require unsafe operations to remain explicit; the Rust 2024 edition warns on this pattern by default.

Official reference:

- https://doc.rust-lang.org/edition-guide/rust-2024/unsafe-op-in-unsafe-fn.html

### Miri

Miri executes Rust MIR while checking classes of undefined behavior such as many invalid memory accesses and aliasing violations. It is highly useful for supported pure-Rust unsafe code, but it cannot validate undocumented semantics of an arbitrary real foreign library.

Official project:

- https://github.com/rust-lang/miri

Do not report `Miri PASS` unless `cargo miri test` (or an explicitly documented equivalent) was actually run on the relevant code path.

## Compiler-error interpretation

These are heuristics for investigation, not one-to-one diagnoses.

| Signal | Boundary question |
|---|---|
| E0382 use of moved value | Is unique ownership represented correctly? |
| E0499 multiple mutable borrows | Is the API exposing more than one mutation path? |
| E0502 mutable/immutable conflict | Does the abstraction mix observation and mutation lifetimes incorrectly? |
| E0515 returned reference to local data | Is a reference escaping its real owner/lifetime? |
| E0277 around `Send`/`Sync` | Is thread movement actually supported by the underlying resource? |
| lifetime mismatch | Is an external lifetime assumption still implicit? |

Do not mechanically refactor based only on an error code. Read the complete diagnostic and the actual ownership contract.

## What RanGate deliberately does not do

- It does not prove arbitrary C/C++ libraries correct.
- It does not claim that fewer `unsafe` blocks automatically means safer code.
- It does not replace code review of unsafe proof obligations.
- It does not add `Send`/`Sync` to make an API convenient.
- It does not use `transmute` as a general escape hatch.
- It does not silence Clippy/compiler errors to reach a green dashboard.

The success criterion is narrower and auditable: fewer parts of the Rust program must understand the dangerous invariant, and independent compiler/test evidence agrees with the new boundary.