# LockScope Pro Test — amendments after run 1

Run 1: GitHub Actions `31817638259`, commit `abf66c29fe62a65e06ce6f0697538553f43533b6`.

The preregistered acceptance criteria remain unchanged. In particular, run 1 already produced one **substantive** failed expectation that cannot be repaired away: on Rust 1.97.1, `std::sync::MutexGuard` explicitly passed to `drop(guard)` before an await still caused a `tokio::spawn` Send-bound failure. The lexical-scope version compiled. Therefore the original `PASS_PRO` gate is already impossible for this experiment. The amended run exists to finish measuring the remaining LockScope mechanisms fairly.

## A1 — semantic family evidence (harness defect)

Observed in run 1:

- the fixture contained many syntactically known lock acquisitions, but normalized semantic output had **zero lock sites**;
- Javis and Ferryman likewise produced zero Tokio sites;
- mini-redis's injected `std::sync::Mutex` site *was* detected, proving the parser and LSP transport were running rather than the source being absent.

Cause: family classification relied too heavily on guard hover text and method-definition URIs; its Tokio registry-path predicate expected `/tokio-/`, which does not match real versioned paths such as `/tokio-1.47.1/`. Alias-heavy hover text also need not contain the fully-qualified family.

Allowed correction:

- add method hover and receiver `textDocument/typeDefinition` evidence;
- recognize versioned `/tokio-*`, `/parking_lot-*`, and `/lock_api-*` paths;
- if a file has syntactic acquisition candidates but semantic classification returns zero, fail with an analyzer-readiness error instead of silently declaring it clean.

No expected finding, repository commit, case count, or threshold changed.

## A2 — isolated Clippy target for Tokio repair (harness defect)

Observed in run 1:

- the Tokio contention repair itself compiled and completed after transformation;
- `cargo clippy --bin tokio_repair_probe -- -D warnings` failed because Cargo also linted the same package's intentionally hazardous `src/lib.rs`, where `std::sync`/parking_lot guards across awaits are deliberate compiler-ground-truth cases.

Allowed correction:

- run the exact same before/after Tokio repair source in a standalone tiny Cargo package with the same pinned Tokio version;
- run strict Clippy there with no `allow` suppression.

No repair logic or acceptance expectation changed.

## Binding evidence retained from run 1

The following are not discarded:

- `std_last_use`: compiler rejected non-Send future as expected;
- `std_drop`: compiler rejected non-Send future **contrary to preregistration** — binding substantive failure;
- `std_scope`: compiled as expected;
- `parking_last_use`: compiler rejected non-Send future as expected;
- mini-redis healthy check/tests passed;
- mini-redis injected guard-across-await was rejected by the compiler;
- the conservative mini-redis repair moved lock acquisition after the independent await and then check/tests passed;
- mini-redis baseline strict Clippy was already red under Rust 1.97.1 for an unrelated `useless_conversion`, so the preregistered baseline-red Clippy rule applied;
- all run-1 jobs stayed inside their runtime budgets.

The amended run may provide additional evidence but cannot turn the original protocol verdict into `PASS_PRO`.