# CrypticShift Hard Pro Test Report

Date: 2026-08-14
Branch: `test/crypticshift-pro-20260814`
Preregistered protocol: `experiments/crypticshift/PRO_TEST_PROTOCOL.md`
Final workflow run: `31791534801`
Final tested commit: `0220ba728c519d5758f3b95ef1c10cda7ce48c0a`

## Verdict

**PASS_PRO.**

CrypticShift passed every preregistered acceptance gate on both Ubuntu 24.04 and macOS 26 arm64 with Rust 1.97.1. The result supports the bounded cryptic-reservoir/release search hypothesis under a deliberately difficult compiler-backed Rust benchmark.

This is strong evidence for continuing the candidate. It is **not** yet evidence that an autonomous LLM using CrypticShift outperforms normal agents on a real repository. The preregistered protocol explicitly requires one real-repository/LLM-generated validation before production SkillQuarry promotion.

## Frozen protocol

The protocol and thresholds were committed before the first pro result was observed.

Search benchmark:

- 11 landscapes total;
- 4 pair-synergy landscapes;
- 2 triple-synergy landscapes;
- 1 dense-decoy landscape;
- 1 deliberately adversarial ranking landscape;
- 3 no-synergy controls;
- real multi-file Rust source was generated for each baseline, singleton and combination;
- candidates entering scoring had to compile, pass Clippy with `-D warnings`, and preserve fixture behavior;
- a singleton was forbidden from Pareto-dominating the baseline;
- pair budget: 3 releases;
- pair+triple budget: 6 releases;
- equal-budget random release baseline;
- strict greedy baseline;
- exhaustive pair/triple search as an upper bound.

Measured architecture-cost vector:

```text
Arc::new count
Mutex::new count
.clone() count
Box<dyn Fn> count
```

A success required Pareto dominance of the baseline rather than a hidden scalar reward.

Semantic torture suite:

1. lifetime/owned-boundary behavior preservation;
2. positive async future `Send` proof;
3. rejection of `MutexGuard` held across `.await` as `!Send`;
4. double mutable borrow rejection;
5. conflicting trait implementation rejection;
6. `Rc<RefCell<_>>` cross-thread rejection;
7. no-default/all-feature matrix;
8. cross-crate workspace/API behavior;
9. real Git conflicting-patch rejection plus disjoint-patch acceptance;
10. no `unsafe` escape hatch.

## Preregistered acceptance gates

```text
non-adversarial positive success >= 85%
overall positive success         >= 70%
advantage over random            >= 20 percentage points
greedy success                   <= 25%
control false positives          == 0
adversarial limitation           must be exposed
semantic torture probes          all pass
runtime                          <= 300 s/platform
```

No threshold, landscape, search budget or search ranking rule was changed after seeing the first result.

## Final results

The search metrics were identical on Ubuntu and macOS:

```json
{
  "landscapes": 11,
  "positive_landscapes": 8,
  "aligned_positive_landscapes": 7,
  "adversarial_positive_landscapes": 1,
  "controls": 3,
  "cryptic_aligned_success_rate": 1.0,
  "cryptic_success_rate": 0.875,
  "greedy_success_rate": 0.0,
  "random_mean_success_rate": 0.5426,
  "control_false_positives": 0,
  "adversarial_successes": 0,
  "semantic_probes": 10,
  "semantic_probes_passed": 10
}
```

Runtime:

- Ubuntu 24.04: **49.83 s**
- macOS 26.5.2 arm64: **66.98 s**

Both are far below the frozen 300 s ceiling.

## Search result interpretation

CrypticShift found every one of the seven non-adversarial improving landscapes under the bounded release budget.

That includes:

- four pair-only synergy landscapes;
- two triple-only synergy landscapes where no singleton could win;
- one dense-decoy landscape where the actual winner was not the top complementarity candidate.

Overall it found 7/8 positive landscapes = **87.5%**.

Strict greedy found **0/8**, because no singleton was allowed to Pareto-dominate the baseline.

Equal-budget random release averaged **54.26%** across positive landscapes.

CrypticShift therefore beat random by **33.24 percentage points**, above the frozen +20 pp requirement.

The three no-synergy controls produced **zero false-positive evolutions**.

## Deliberate adversarial failure

The adversarial landscape was intentionally constructed so that singleton tradeoff complementarity was misleading.

The exhaustive winner was:

```text
CD
```

CrypticShift ranked and tested only:

```text
AB
BC
AD
```

under the frozen pair budget of 3, so it returned no evolution.

This is an important limitation rather than an embarrassment: the heuristic is not an oracle. Fitness-vector complementarity is useful but does not prove actual patch compatibility or higher-order synergy.

## Semantic torture evidence

Final Ubuntu and macOS runs both passed all 10 probes.

Observed negative compiler proofs included:

- async `MutexGuard` held across `.await` rejected because the future is not `Send`;
- double mutable borrow rejected with E0499;
- conflicting blanket/specific trait implementation rejected with E0119;
- `Rc<RefCell<_>>` moved across a thread boundary rejected with E0277.

Positive probes also passed:

- owned/lifetime-boundary behavior equivalence;
- valid `Send` async future;
- feature matrix under no-default and all-features;
- multi-crate workspace/API behavior;
- real Git patch compatibility check (`conflict=True`, `disjoint=True`);
- no generated positive fixture used `unsafe`.

## First pro run and fixture-only correction

Initial workflow run: `31791393359`.

Its search component already satisfied all frozen search gates on Ubuntu:

```text
CrypticShift overall:    87.5%
CrypticShift aligned:   100.0%
Greedy:                   0.0%
Random mean:             54.26%
Control false positives: 0
Adversarial successes:    0
```

Nine of ten semantic probes passed.

The sole failure was the positive async `Send` fixture. Its helper:

```rust
fn assert_send<T: Send>(_: &T) {}
```

was called only from `#[cfg(test)]` code but was itself compiled in the normal library target. Because the fixture deliberately runs Clippy with `-D warnings`, Clippy rejected the unused helper as `dead_code` before the intended positive proof could count.

The only correction was to make that helper test-only:

```rust
#[cfg(test)]
fn assert_send<T: Send>(_: &T) {}
```

The fix was isolated in `pro_test_v2.py`. It did not alter:

- any landscape;
- any fitness vector;
- any search ranking;
- any release budget;
- any random baseline;
- any acceptance threshold;
- any negative semantic probe.

The corrected full cross-platform run was then executed from scratch and passed on both platforms.

## Platforms

Ubuntu final job:

- Ubuntu 24.04.4 LTS
- rustc 1.97.1
- cargo 1.97.1
- Python 3.12.3
- Git 2.54.0
- final job `94739314264`

macOS final job:

- macOS 26.5.2, build 25F84
- hosted image `macos-26-arm64`
- rustc 1.97.1
- cargo 1.97.1
- Python 3.14.6
- Git 2.55.0
- final job `94739314180`

Both jobs concluded `success` and emitted `"verdict": "PASS_PRO"`.

## What is genuinely covered

The test directly exercises:

- bounded search rather than exhaustive search pretending to be intelligent;
- pair and triple synergies;
- decoy candidates;
- a deliberate heuristic failure;
- no-solution controls;
- Pareto multi-objective selection;
- compiler validity;
- Clippy cleanliness;
- behavior preservation;
- lifetime-oriented boundary transformation;
- async/Send semantics;
- borrow-checker rejection;
- trait coherence;
- thread confinement;
- feature configurations;
- multi-crate workspaces;
- Git patch conflicts;
- avoidance of `unsafe` escape hatches;
- deterministic search ordering;
- Linux/macOS reproducibility;
- runtime ceiling.

## What is NOT covered

No finite test can cover "all Rust" or all agent behavior. Specifically this pro test still does not prove:

- real LLM-generated variants are sufficiently diverse or correct;
- an LLM can identify the useful structural dimensions in a large unfamiliar repository;
- patch reconciliation remains robust across hundreds of files;
- proc macros/build scripts/platform FFI are handled;
- runtime performance improves merely because static architecture-cost proxies improve;
- the same heuristic works when the reservoir contains dozens of variants;
- the method beats strong modern coding agents on naturally occurring historical refactors.

## Independent replication attempt (2026-08-14)

Reproduced on the maintainer's Linux machine with the pinned Rust 1.97.1. The
harness printed **FAIL_PRO** — and that verdict was wrong: the machine has `rustc`
and `cargo` but no C linker, so every probe that must compile *and link* failed,
including `lifetime_owned_boundary`, `async_send_positive`, `feature_matrix_positive`
and `workspace_api_positive`. The negative probes, which only need a compile error,
passed as expected.

That is a defect in the harness, not evidence against the method: a fact about one
machine was reported as a judgement about CrypticShift. Both harnesses now check
for `cargo`, `rustc` and `cc` first and exit with `NOT_RUN` (exit code 2) when any
is missing, which is distinct from an evaluated failure (exit code 1).

The CI evidence stands unchanged: run `31791534801`, commit
`0220ba728c519d5758f3b95ef1c10cda7ce48c0a`, green on both `ubuntu-24.04` and
`macos-latest`, verified through the GitHub API rather than taken from this report.

## Final decision

**GO to one final real-repository / LLM-authored validation.**

Do **not** yet merge CrypticShift as a production SkillQuarry skill solely from this synthetic pro benchmark.

If the real-repository test preserves a meaningful advantage over greedy/random baselines without exploding patch cost or false positives, CrypticShift should be promoted into a production skill. If that final validation fails, keep the research evidence but do not ship it.
