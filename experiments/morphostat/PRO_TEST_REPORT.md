# Morphostat Pro Test Report

Date: 2026-08-14
Branch: `test/morphostat-pro-20260814`
Repository: `BEKO2210/SkillQuarry`

## Verdict

The Morphostat concept is promising enough to continue, but the original regex/TOML prototype is not suitable as the production detector.

The controlled A/B matrix showed that a stored structural target can detect repository changes that `cargo check`, strict Clippy, and `cargo test` all accept. An adversarial Rust-syntax evaluation then demonstrated that the prototype scanner has serious false-negative gaps. A compiler-native feasibility follow-up showed that Cargo metadata and rustdoc JSON close five of those seven demonstrated gaps without producing a false positive in the included private-implementation control.

The remaining unresolved class is intra-crate implementation coupling expressed through arbitrary resolved paths such as `crate::audit::...` or aliases such as `use crate as root; root::audit::...`. Rustdoc JSON does not encode function bodies as a call/dependency graph, so production Morphostat must not claim complete intra-crate coupling detection until that dimension is implemented using a compiler/HIR or rust-analyzer-derived source.

## Environment

Final pro workflow run: `31763955111`
Final job: `94655888075`

Observed environment:

- Ubuntu 24.04.4 LTS
- stable `rustc 1.97.1 (8bab26f4f 2026-07-14)`
- stable `cargo 1.97.1 (c980f4866 2026-06-30)`
- nightly `rustc 1.99.0-nightly (c98d0cb27 2026-08-12)` from `nightly-2026-08-13`
- Python 3.12.3

## Baseline comparison

For each controlled mutation the standard Rust gate was:

```bash
cargo check --workspace --all-targets
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --quiet
```

Morphostat compared a previously extracted target morphology with the mutated repository.

## Controlled 22-scenario A/B matrix

Final metrics from the clippy-clean run:

```json
{
  "scenarios": 22,
  "structural_cases": 15,
  "control_cases": 7,
  "morphostat_structural_detected": 15,
  "standard_rust_structural_detected": 1,
  "additional_structural_detections_while_standard_green": 14,
  "false_positives": 0,
  "target_morphology_bytes": 1302,
  "healthy_source_bytes": 2010,
  "morphology_to_source_ratio": 0.6478
}
```

Interpretation:

- Morphostat detected all 15 curated structural mutations.
- Fourteen of those fifteen mutations still passed all three standard Rust gates.
- The only structural mutation caught by the standard gate was a deliberately removed declared dependency that made compilation fail.
- No Morphostat false positive occurred across the healthy baseline and six non-structural controls.
- A behavior-only mutation was intentionally invisible to Morphostat and was caught by `cargo test`, demonstrating complementary rather than duplicate sensing.

The 0.6478 morphology/source ratio is a measurement for this tiny synthetic workspace only. It is not evidence of strong compression at realistic repository scale.

## Structural cases

The controlled structural cases were:

1. direct new workspace dependency from `app` to `storage`;
2. new `policy -> audit` internal module edge;
3. internal module cycle;
4. public function signature drift;
5. private function widened to public;
6. public item removed;
7. public item added;
8. default Cargo feature set changed;
9. Cargo feature removed;
10. crate renamed from `storage` to `persistence`;
11. `storage` crate absorbed into another crate;
12. new workspace crate added;
13. public module renamed;
14. new public module added;
15. required dependency declaration removed.

## Controls

Morphostat correctly stayed quiet for:

- healthy baseline;
- behavior-only arithmetic bug;
- private helper refactor;
- comment-only change;
- private algorithm refactor with identical behavior;
- extra test only;
- import reordering only.

The behavior-only arithmetic bug failed the Rust test stage, as intended.

## Failed first pro run and fix

Run `31763600026` failed the experiment's acceptance threshold.

The problem was in the fixture, not in Morphostat: two `pub(crate)` marker constants existed only to support later mutations and were unused in the healthy baseline. Because the comparison gate used `cargo clippy -- -D warnings`, the healthy baseline itself failed Clippy. This incorrectly made several structural mutations appear detectable by the standard Rust gate.

Fix: the baseline was changed to consume both marker constants without changing behavior. The complete matrix was rerun from scratch. Run `31763672324` then passed with the final 15/15, 14-additional, 0-false-positive metrics above.

This failed run is retained as evidence; it was not deleted or reclassified as a success.

## Adversarial syntax evaluation

After the successful curated matrix, the prototype scanner was deliberately attacked with valid Rust forms that its simple line-oriented extraction might miss.

Run `31763786791` demonstrated seven silent prototype misses:

1. direct qualified path: `crate::audit::...`;
2. crate alias path: `use crate as root; root::audit::...`;
3. target-specific Cargo dependency table;
4. public trait method signature change;
5. public struct field type change;
6. macro-generated public API change;
7. multiline public function signature change.

All seven variants passed the standard Rust gate and were missed by the regex/TOML prototype.

This result invalidates the regex prototype as a production implementation. It does not invalidate the target-morphology concept.

## Compiler-native feasibility test

Final run `31763955111` added a separate compiler-native feasibility gate.

### Cargo metadata

Command source:

```bash
cargo metadata --format-version 1 --no-deps
```

Result for the previously missed target-specific dependency:

```json
{
  "case": "target_specific_dependency",
  "source": "cargo_metadata",
  "detected": true,
  "target_preserved": true
}
```

The emitted dependency metadata preserved the `cfg(unix)` target and changed the semantic metadata signature.

### Rustdoc JSON

The feasibility test used pinned `nightly-2026-08-13` and invoked:

```bash
cargo +nightly-2026-08-13 rustdoc -p <package> --lib -Z unstable-options --output-format json
```

The emitted rustdoc JSON reported format version `61` in both healthy and mutated variants.

After removing source-position/documentation noise, the compiler-produced semantic graph changed for all four previously missed public-API cases:

- trait method signature drift: detected;
- public struct field type drift: detected;
- macro-generated public API drift: detected;
- multiline public function signature drift: detected.

Negative control:

- private helper implementation-only refactor: not detected, as expected.

Compiler-native feasibility result: 5 positive cases detected, 1 negative control quiet, 0 failures.

## What remains unsolved

Two demonstrated blind spots remain after the Cargo metadata + rustdoc JSON feasibility test:

- direct intra-crate implementation dependency expressed as a qualified path;
- the same dependency hidden behind a crate alias.

These require resolved implementation-body relationships, not only Cargo package metadata or public rustdoc structure. A production design should use compiler/HIR or rust-analyzer-derived data for this layer. Until that is implemented and tested, Morphostat must describe intra-crate implementation-edge coverage as partial.

Other untested dimensions include:

- procedural macro expansion across third-party crates;
- build-script-generated Rust;
- platform matrices beyond the Linux pro runner;
- large real-world workspaces;
- incremental morphology updates;
- deliberate/approved architecture evolution and target migration;
- automatic repair/regeneration by an AI agent;
- precision/recall on naturally occurring historical regressions rather than injected mutations.

## Production direction justified by this test

Do not ship the regex prototype.

A credible Morphostat v2 architecture should combine:

1. `cargo metadata --format-version 1` for workspace, dependency, target and feature morphology;
2. compiler-produced rustdoc JSON for public/reachable API morphology;
3. a resolved compiler/HIR or rust-analyzer source for intra-crate implementation relationships;
4. conventional build/lint/test evidence as an orthogonal behavioral sensor;
5. explicit approval/versioning for intentional morphology changes instead of automatically treating every structural change as damage.

## Reproduction

On branch `test/morphostat-pro-20260814`:

```bash
cd experiments/morphostat
python3 pro_test_v2.py
python3 redteam.py
python3 compiler_native_feasibility.py
```

The final GitHub Actions workflow is `.github/workflows/morphostat-pro-eval.yml`.

## Scientific interpretation

The experiment supports this narrow software hypothesis:

> A separately stored structural target can detect classes of repository drift that a passing compiler, linter and behavioral test suite do not necessarily identify.

It does not establish that planarian regeneration and software architecture are mechanistically equivalent. The biological system is the design inspiration; the software claim stands or falls on the engineering measurements above.
