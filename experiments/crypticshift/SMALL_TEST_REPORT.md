# CrypticShift Small Test Report

Date: 2026-08-14
Branch: `test/crypticshift-small-20260814`
Final workflow run: `31789846837`
Final job: `94734064170`
Tested commit: `1fb16b52197afd5d1909adb8004ba908ed426fd2`

## Verdict

**PASS_SMALL — continue to a harder pro test, but do not ship as a SkillQuarry skill yet.**

The small experiment supports the narrow search hypothesis behind CrypticShift: retaining compiler- and test-valid but individually non-dominating structural variants can enable an equal-budget combination search to escape landscapes where a greedy one-step refactor cannot move.

This is a synthetic compiler-backed experiment. It is not evidence that CrypticShift improves real autonomous Rust refactors yet.

## Environment

Observed in GitHub Actions:

- Ubuntu 24.04.4 LTS
- rustc 1.97.1
- cargo 1.97.1
- Python 3.12.3

Every evaluated candidate was required to pass:

```bash
cargo check --quiet
cargo clippy --quiet -- -D warnings
cargo test --quiet
```

Behavior was held constant by the fixture tests.

## Fitness vector

The generated Rust candidates were measured directly from source for four concrete architectural-cost proxies:

- `Arc::new` count
- `Mutex::new` count
- `.clone()` count
- `Box<dyn Fn>` count

Baseline:

```json
{"arc":3,"mutex":3,"clone":3,"box_dyn":3}
```

Lower is better. A candidate counts as an evolution only when it Pareto-dominates the baseline.

## Search protocol

For each landscape:

1. four singleton structural variants were compiled, clippied and tested;
2. no valid singleton was allowed to Pareto-dominate the baseline;
3. all compiler-valid singletons formed the cryptic reservoir;
4. CrypticShift ranked variant pairs by opposite-sign fitness-vector complementarity;
5. only the top **2** pairs could be released/tested;
6. an equal-budget random-release baseline also selected 2 pairs;
7. greedy search accepted only a singleton Pareto improvement.

All pair candidates were separately compiled, clippied and tested so the winner was not a paper-only fitness calculation.

## Final metrics

```json
{
  "landscapes": 8,
  "synergy_landscapes": 6,
  "controls": 2,
  "pair_budget_after_reservoir": 2,
  "crypticshift_synergy_successes": 5,
  "crypticshift_synergy_success_rate": 0.8333,
  "crypticshift_aligned_success_rate": 1.0,
  "crypticshift_adversarial_success_rate": 0.0,
  "greedy_synergy_success_rate": 0.0,
  "random_release_mean_success_rate": 0.3225,
  "control_false_positives": 0,
  "all_rust_candidates_valid": true
}
```

Interpretation:

- CrypticShift found 5/6 hidden improving combinations under a two-pair budget.
- It found all 5 landscapes where single-variant complementarity was genuinely informative.
- Greedy search found 0/6 because no singleton improved the full Pareto vector.
- Equal-budget random release succeeded about 32.25% on average.
- CrypticShift produced 0 false-positive evolutions on the two no-synergy controls.
- The deliberately adversarial landscape was missed, as intended: the true compatible pair was ranked third while the top-ranked pair had strong but misleading complementarity.

The adversarial miss is important evidence that the heuristic is not magic and that complementarity is not the same thing as compatibility.

## Failed preliminary run

The first run was rejected because the experiment fixture itself violated its declared setup:

- one singleton accidentally Pareto-dominated baseline;
- two generated candidates were structurally duplicate;
- the intended adversarial winner was still ranked second and therefore remained inside the pair budget.

Those landscape-definition errors were corrected without changing pair budget, search algorithm, or acceptance thresholds.

A subsequent wrapper-only run failed before candidate evaluation due to accidental recursive monkey-patching. The final run fixed only that invocation bug and used the already-corrected landscapes unchanged.

## What this test supports

Supported narrow claim:

> When individually valid structural alternatives expose complementary tradeoffs, preserving them instead of greedily discarding them can make a small bounded combination search substantially more successful than one-step greedy search and equal-budget random release.

## What this test does NOT support

- no real repository refactor was performed;
- no LLM generated the variants;
- compatibility was represented by a controlled integration model;
- the fitness vector is intentionally small;
- only pair releases were tested, not triples;
- no compile-failing intermediate variants were retained;
- no real lifetime/borrow-checker/async migration was tested;
- no runtime-performance benchmark was part of selection;
- the complementarity heuristic failed the deliberately adversarial case.

## Decision

**Continue to a pro test. Do not merge CrypticShift as a production skill yet.**

The next test should use real Rust source transformations in one or more nontrivial fixtures where the variants are independently authored, combined as patches rather than generated from a cost table, and judged against greedy, random-restart and exhaustive upper-bound baselines under the same compile/test budget.
