# Morphostat rust-analyzer Semantic Feasibility Report

Date: 2026-08-14
Branch: `test/morphostat-pro-20260814`
Final workflow run: `31764438526`
Final job: `94657275655`
Commit tested: `9b16df06c1f74855941c6bb055efbb831b4511f8`

## Verdict

PASS for the two previously unresolved intra-crate path forms in the synthetic fixture.

The production direction remains feasible: use rust-analyzer semantic definition resolution to derive intra-crate module relationships instead of parsing Rust paths with regular expressions.

This result is not evidence that the implementation is ready for production or that all Rust relationship forms are covered.

## Environment

Observed in GitHub Actions:

- Ubuntu 24.04.4 LTS
- rustc 1.97.1 (8bab26f4f 2026-07-14)
- cargo 1.97.1 (c980f4866 2026-06-30)
- rust-analyzer 1.97.1 (8bab26f 2026-07-14)
- nightly rustc 1.99.0-nightly (c98d0cb27 2026-08-12), pinned as nightly-2026-08-13 for the separate rustdoc JSON test
- Python 3.12.3

## Method

The experiment starts rust-analyzer as an LSP server over stdio and issues standard `textDocument/definition` requests for identifier tokens. Returned definition URIs are mapped back to Rust source modules. Cross-module definition relationships form a semantic edge set.

The first implementation queried definitions immediately after LSP initialization. Run `31764346944` failed because rust-analyzer had not finished loading the Cargo workspace: even known baseline edges such as `policy -> value` and `audit -> value` were absent. The failed run is retained.

The corrected implementation adds an explicit readiness gate. The fixture has known baseline semantic edges, so an empty graph is treated as not-ready and retried for up to 15 seconds. No guessed sleep duration is used as acceptance evidence.

## Final results

### Direct qualified path

Mutation:

```rust
let _ = crate::audit::AUDIT_MARKER;
```

Healthy semantic edges:

```text
__root__->audit
__root__->policy
__root__->value
audit->value
policy->value
```

Mutated semantic edges:

```text
__root__->audit
__root__->policy
__root__->value
audit->value
policy->audit
policy->value
```

Result: PASS. The new `policy->audit` edge was detected.

### Crate-alias path

Mutation:

```rust
use crate as root;
let _ = root::audit::AUDIT_MARKER;
```

Healthy semantic edges:

```text
__root__->audit
__root__->policy
__root__->value
audit->value
policy->value
```

Mutated semantic edges:

```text
__root__->audit
__root__->policy
__root__->value
audit->value
policy->audit
policy->value
```

Result: PASS. The alias still resolved to the same `policy->audit` semantic edge.

### Negative control: private helper refactor

A private helper was introduced and used entirely inside `policy.rs` without changing cross-module dependencies.

Healthy and mutated semantic edge sets were identical:

```text
__root__->audit
__root__->policy
__root__->value
audit->value
policy->value
```

Result: PASS. No structural drift was reported.

## Final workflow status

Run `31764438526` completed successfully. The following gates all passed on the same commit:

1. syntax check;
2. 22-case A/B pro test;
3. adversarial Rust syntax evaluation;
4. Cargo metadata + rustdoc JSON compiler-native feasibility evaluation;
5. rust-analyzer semantic edge evaluation with readiness gate.

The earlier 22-case matrix remains unchanged: 15 curated structural cases detected by Morphostat, 14 of them while the standard Rust gate remained green, and zero false positives across the seven controls in that matrix.

## Remaining limitations

The LSP proof is deliberately narrow. Before turning Morphostat into a SkillQuarry skill, the following still need testing:

- large real-world workspaces and performance when many definition requests are required;
- nested modules and `mod.rs`/inline module combinations;
- cfg-dependent source graphs across Linux and macOS;
- macro-expanded implementation-body relationships;
- proc macros and build-script-generated code;
- re-exports and ambiguous names across crates;
- intentional architecture evolution and approval/versioning of target morphology;
- rust-analyzer version changes and LSP behavior changes;
- crash/restart behavior while semantic extraction is in progress;
- precision/recall on naturally occurring historical repository regressions rather than only injected mutations.

The current identifier scan is only a way to choose LSP query positions. Semantic truth comes from rust-analyzer's resolved definitions; the regex scanner is not used to decide where a symbol resolves.

## Reproduction

```bash
cd experiments/morphostat
python3 pro_test_v2.py
python3 redteam.py
python3 compiler_native_feasibility.py
python3 lsp_semantic_feasibility_v2.py
```

The GitHub Actions workflow is `.github/workflows/morphostat-pro-eval.yml`.
