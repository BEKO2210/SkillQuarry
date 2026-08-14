# CrypticShift Pro Test Protocol

Date: 2026-08-14
Branch: `test/crypticshift-pro-20260814`
Status: **PREREGISTERED BEFORE THE FIRST PRO RUN**

## Purpose

Test the core CrypticShift claim under a deliberately hostile compiler-backed Rust evaluation. The test must not be tuned after observing results.

## Search benchmark

The harness contains 11 independent search landscapes built from real multi-file Rust source transformations:

- four pair-synergy landscapes;
- two triple-synergy landscapes;
- one dense-decoy landscape;
- one deliberately adversarial ranking landscape;
- three no-synergy controls.

Every baseline, singleton and combination candidate that enters scoring is compiled and behavior-tested with Rust. Singletons are not allowed to Pareto-dominate the baseline.

The measured fitness vector is extracted from the generated Rust source itself:

- `Arc::new` count;
- `Mutex::new` count;
- `.clone()` count;
- `Box<dyn Fn>` count.

Lower is better. An evolution requires Pareto dominance, not a scalar score.

CrypticShift ranks releases only from singleton tradeoff complementarity. It is not allowed to inspect the measured combination fitness before selecting a candidate. Pair landscapes get 3 release attempts. Pair+triple landscapes get 6 release attempts.

Baselines:

1. strict greedy: accepts only a singleton Pareto improvement;
2. equal-budget random release;
3. exhaustive pair/triple search as an upper bound.

## Semantic torture suite

The pro run additionally requires all of these independent probes:

1. lifetime/owned-boundary behavior preservation;
2. positive `async` future `Send` proof;
3. negative `async`/`MutexGuard`-across-`await` rejection;
4. borrow-checker double-mutable-borrow rejection;
5. trait-coherence conflicting-impl rejection;
6. `Rc<RefCell<_>>` thread-confinement rejection;
7. default/no-default/all-feature compilation and tests;
8. cross-crate workspace/API behavior preservation;
9. real Git patch conflict detection plus disjoint-patch acceptance;
10. no `unsafe` escape hatch in generated positive fixtures.

Negative probes count as PASS only when Rust rejects the intended invalid shape for the intended semantic reason.

## Frozen acceptance gates

A pro result is `PASS_PRO` only if all are true:

- non-adversarial positive success rate >= **85%**;
- overall positive success rate >= **70%**;
- CrypticShift exceeds equal-budget random release by >= **20 percentage points**;
- greedy success rate <= **25%**;
- no-synergy controls produce **0 false-positive evolutions**;
- the adversarial case must expose at least one ranking limitation rather than accidentally making the heuristic look perfect;
- every semantic torture probe passes;
- full runtime <= **300 seconds** per platform.

These thresholds, budgets, landscapes and probe classes are frozen before the first pro workflow result is observed.

## Platform requirement

Run the same test on:

- Ubuntu 24.04;
- macOS latest hosted runner.

Rust is pinned to 1.97.1 with Clippy. Python is used only as the experiment harness.

## Interpretation rule

- `PASS_PRO` means the search hypothesis deserves one real-repository/LLM-generated validation before production SkillQuarry promotion.
- `FAIL_PRO` means do not ship CrypticShift as a production skill and do not loosen the gates after seeing the failure.
