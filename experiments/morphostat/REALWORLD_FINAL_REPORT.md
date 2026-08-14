# Morphostat Real-World Final Test Report

Date: 2026-08-14
Branch: `test/morphostat-pro-20260814`
Target repository: `BurntSushi/ripgrep`
Pinned target commit: `3fce3b5bb0236da2df6d99672afb8a719642eca7`

## Verdict

**NO-GO for promotion to a SkillQuarry skill at this stage.**

The Morphostat concept remains technically promising based on the synthetic and compiler-native evaluations, including Cargo metadata, rustdoc JSON, and rust-analyzer semantic resolution. However, the planned final real-world mutation matrix did not reach the morphology comparison stage because the pinned upstream baseline could not satisfy the deliberately strict standard-Rust gate under the chosen current toolchain.

It would be dishonest to report real-world precision, recall, false-positive rate, or runtime from this test, because those measurements were never produced.

## What was intended

The final experiment was designed to use a real multi-crate Rust project rather than a synthetic fixture.

The selected target was ripgrep at commit:

```text
3fce3b5bb0236da2df6d99672afb8a719642eca7
```

The planned morphology combined:

1. Cargo metadata for the full ripgrep workspace;
2. rustdoc JSON for the public API of the `ignore` crate;
3. rust-analyzer definition resolution for cross-module dependencies originating from `ignore::overrides`.

The experiment contained 11 structural mutations and 5 controls. It also required three unchanged baseline extractions to be identical before any mutation result could count.

## Final acceptance gates

The baseline standard-Rust comparison was intended to require:

```bash
cargo check --workspace --lib --bins --tests
cargo clippy -p ignore --all-targets -- --no-deps -D warnings
cargo test -p ignore --quiet
```

No mutation was allowed to be scored until the unchanged upstream baseline passed those gates.

## Attempt 1

Workflow run: `31764943153`

The original check command used:

```bash
cargo check --workspace --all-targets
```

This failed because ripgrep contains a benchmark using:

```rust
#![feature(test)]
```

Stable Rust therefore rejected the benchmark with `E0554`.

This was a harness error: `--all-targets` pulled a known Nightly-only benchmark into a Stable baseline check.

The check command was corrected to exclude benches while retaining workspace libraries, binaries, and tests.

## Attempt 2

Workflow run: `31765042862`

The corrected `cargo check` passed.

Clippy still failed because Cargo/Clippy included workspace path dependencies. `globset` produced existing Clippy warnings under Rust 1.97.1, which became errors because the experiment deliberately used `-D warnings`.

The official Clippy documentation states that workspace path dependencies are included when running Clippy for a package and documents `--no-deps` for restricting linting to the selected crate.

The final baseline therefore used `--no-deps`.

## Attempt 3 — final

Workflow run: `31765138590`

This was declared the final gate configuration before execution. No further gate changes are accepted as part of this experiment.

Observed toolchain:

- Ubuntu 24.04.4 LTS
- rustc 1.97.1
- cargo 1.97.1
- rust-analyzer 1.97.1
- nightly rustc 1.99.0-nightly from `nightly-2026-08-13`
- Python 3.12.3

Result:

```text
cargo check --workspace --lib --bins --tests
PASS
```

Final Clippy baseline:

```bash
cargo clippy -p ignore --all-targets -- --no-deps -D warnings
```

Result: **FAIL**.

The failure was inside the unchanged pinned `ignore` crate itself. The log contained existing Rust 1.97 Clippy diagnostics such as `clippy::useless_vec`; approximately 120 diagnostics were reported before compilation of the `ignore` lib test failed.

Because the unchanged upstream baseline failed, the script terminated before extracting the three baseline morphologies and before running any of the 11 structural mutations or 5 controls.

## What this result means

This run does **not** demonstrate a Morphostat false positive or false negative.

It demonstrates that the final real-world experiment, as specified, was not a valid measurement environment for Morphostat because its prerequisite baseline was not clean under the selected current Clippy policy.

Changing the methodology now — for example by:

- ignoring existing baseline warnings,
- comparing only newly introduced diagnostics,
- pinning an older Clippy version,
- removing `-D warnings`, or
- choosing a different repository

could be reasonable in a future experiment, but doing so after declaring the final acceptance gate would move the goalposts. This report therefore does not do that.

## Evidence that remains valid from earlier tests

Earlier experiments on the same branch remain useful but are not substitutes for the failed real-world final validation:

- controlled 22-scenario synthetic A/B matrix: 15/15 curated structural changes detected, 14 while standard Rust gates stayed green, 0 false positives in seven controls;
- adversarial syntax test: the original regex prototype missed 7/7 deliberately difficult Rust forms and was rejected;
- Cargo metadata + rustdoc JSON feasibility: five previously missed semantic cases detected with one private-refactor negative control remaining quiet;
- rust-analyzer semantic feasibility: direct `crate::audit` and crate-alias paths both resolved to the expected new module edge while a private same-module helper did not change the edge graph.

These results justify keeping the research branch. They do not justify shipping Morphostat as a finished SkillQuarry skill.

## Decision

**Park Morphostat as research. Do not merge it as a production SkillQuarry skill yet.**

The next attempt, if the idea is revisited, should define a baseline-delta methodology before selecting the real-world repository and should test naturally occurring historical architectural changes, not only injected mutations.

For the current SkillQuarry roadmap, move on to the next biological skill candidate.
