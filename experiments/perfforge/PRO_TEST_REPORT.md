# PerfForge Pro Test Report

Date: 2026-08-15
Branch: `test/perfforge-pro-20260815`
Small-test result: `PASS_SMALL`
Frozen pro protocol commit: `aaa09d9161ed2abaa1927c0b3001ebddbb6e859b`
Initial workflow commit: `ca6c9e5e56f676e092ba5906f0a7a6370e22bd17`
A1 synthetic fixture amendment: `730cee0c8787a0cc1cc7547d449f150b6584c351`
A1 workflow commit: `93f729ed9a3648f794d55f487f1f558e2fa4d53e`
Initial workflow run: `31849318020`
Final evaluated workflow run: `31849482015`

## Binding verdict

**FAIL_PRO — do not promote PerfForge to a production SkillQuarry skill from this design.**

The small test established that correctness, memory and multi-workload gates can reject spectacular but invalid benchmark wins. The harder test exposed two production-level problems that the small test did not cover:

1. the near-threshold statistical protocol is not robust enough across CI platforms with only nine warm paired samples;
2. a performance claim is inseparable from its workload. A commit known to fix a performance pathology can legitimately be slower on a different workload, so historical commit labels are not a universal performance oracle.

No acceptance threshold, expected label or benchmark workload was changed after a substantive result.

## Frozen gate

The pro protocol required:

- separate baseline and candidate processes;
- separate Git worktrees for real repositories;
- randomized AB/BA order;
- 9 warm paired synthetic samples plus 3 cold process pairs;
- 2,000 fixed-seed paired bootstrap resamples on log speed ratios;
- primary lower 95% speedup bound >= 1.08;
- no workload median regression > 1.20x;
- no cold-start regression > 1.25x;
- synthetic RSS increase <= 32 MiB;
- exact semantic digests;
- exact synthetic 8/8 on Ubuntu and macOS;
- exact real-repository 3/3.

`PASS_PRO` required every binding gate.

## Initial run and allowed A1 amendment

Workflow `31849318020` failed in both synthetic jobs before any candidate was measured. The final fixture was constructed with:

```python
dict(**base, drift=True)
```

while `base` already contained `drift=False`, causing Python to raise:

```text
TypeError: dict() got multiple values for keyword argument 'drift'
```

This happened before `synthetic_cases()` could run a single measurement. Under the preregistered integrity rule, this was an infrastructure/harness-construction defect rather than a candidate result.

A1 changed only that fixture construction to normal mapping override syntax. It did not change:

- a threshold;
- an expected label;
- a workload;
- a measurement function;
- bootstrap logic;
- a real-repository test.

The real-repository job from the initial run had no dependency on the broken synthetic fixture and therefore remained substantive evidence.

## Final synthetic run

Workflow: `31849482015`

### Ubuntu 24.04 — PASS_SYNTHETIC

Exact classification: **8/8**
False accepts: **0**
False rejects: **0**
Runtime: **5.180 s**

Selected results:

| Case | Expected | Verdict | Evidence |
|---|---|---|---|
| near_14 | ACCEPT | ACCEPT | median 1.194x; LB95 1.167x |
| near_25 | ACCEPT | ACCEPT | median 1.269x; LB95 1.210x |
| near_5 | REJECT | REJECT | LB95 0.979x |
| wrong_but_fast | REJECT | REJECT | 1.414x median but semantic digest changed |
| memory_for_speed | REJECT | REJECT | +40,058,880 RSS bytes |
| cold_warm_tradeoff | REJECT | REJECT | warm ~1.197x but cold 5.450x slower |
| benchmark_overfit | REJECT | REJECT | large 1.264x faster; small 2.069x slower |
| identical_noise | REJECT | REJECT | LB95 1.004x |

### macOS 26 arm64 — FAIL_SYNTHETIC

Exact classification: **7/8**
False accepts: **0**
False rejects: **1 (`near_25`)**
Runtime: **4.532 s**

`near_25` was the binding failure:

```text
median speedup:     1.255x
geometric mean:     1.098x
bootstrap LB95:     0.812x
required LB95:      1.080x
verdict:            REJECT
expected:           ACCEPT
```

The candidate had the intended lower work count and a median around +25%, but process-level variation was large enough that the frozen confidence gate could not prove the claim. The test therefore records a false reject rather than changing sample count, threshold, bootstrap method or label after seeing the result.

Other important macOS cases behaved correctly:

- `near_14`: ACCEPT, LB95 1.112x;
- `near_5`: REJECT, LB95 1.020x;
- wrong-but-fast: semantic REJECT;
- memory-for-speed: REJECT, +50,413,568 RSS bytes and cold regression;
- cold/warm tradeoff: REJECT, cold 5.008x slower;
- benchmark overfit: REJECT, small workload 2.071x slower;
- identical noise: REJECT, LB95 0.957x.

### Statistical conclusion

The current nine-sample process protocol is good at rejecting large invalid wins but is not stable enough to certify modest improvements across heterogeneous CI runners. A production design needs an adaptive or precision-targeted sampling rule declared before measurement, rather than a fixed tiny sample count.

## Real repositories

The initial real run and final real run agreed on the classification pattern: **2/3**, `FAIL_REAL`.

Final real runtime: **53.059 s**, below the frozen 900 s budget.

### serde_json unicode escape optimization — PASS

Candidate: `86d0e114e1370deb0b00cc97f5aec8c3869d835e`
Parent: `cf771a0471dd797b6fead77e767f2f7943740c98`
Expected: ACCEPT
Verdict: ACCEPT

Final run:

```text
semantic digest:    equal
base tests:         PASS
candidate tests:    PASS
median speedup:     1.159x
geometric mean:     1.162x
LB95:               1.153x
```

The historical commit message reported roughly +15% when parsing unicode escapes into `String`; the isolated worktree measurement reproduced that direction and cleared the frozen +8% lower-bound gate.

### serde_json performance-neutral change — PASS control

Candidate: `236cc8247d32a5cb337850d75f68265fdb4bc14e`
Parent: `2f28d106e68e214cfa19043e65b1bd178b3c2ced`
Expected: REJECT
Verdict: REJECT

Final run:

```text
semantic digest:    equal
base tests:         PASS
candidate tests:    PASS
median speedup:     0.972x
LB95:               0.969x
```

The commit says it does not affect performance; the gate correctly found no optimization evidence.

### Lodash large-string trim — binding failure and important lesson

Candidate: `c4847ebe7d14540bb28a8b932a9ce1b9ecbfee1a`
Parent: `3469357cff396a26c363f8c1b5a91dde28ba4b1c`
Expected by the frozen protocol: ACCEPT
Verdict: REJECT

Final run:

```text
semantic digest:    equal
median speedup:     0.094x
geometric mean:     0.095x
LB95:               0.091x
```

On the frozen workload, the candidate was roughly 10.7x slower than its parent. The initial run independently showed the same direction and an even larger slowdown.

The commit itself replaces a broad trim regex with a right-to-left whitespace scan and adds ReDoS regression tests. Those upstream regression cases put very large whitespace **inside** non-whitespace boundary characters, for example conceptually:

```text
A + 50,000 spaces + A
```

The frozen PerfForge workload instead contained very large leading and trailing whitespace around a short token. That is a different performance surface, and the new character-by-character end scan can be slower there.

This does not justify relabeling the preregistered test. It demonstrates the missing architectural requirement:

> A performance claim must name the workload distribution and objective it applies to. A commit message or benchmark result is not a universal oracle that a patch is faster for all valid inputs.

This is a substantive test-design miss and a useful product finding.

## What still worked

Even though the binding pro verdict is red, the mechanism retained several useful properties:

- zero false accepts in the final synthetic jobs;
- semantic cheating remained blocked;
- memory-for-speed remained blocked;
- cold-start regressions remained blocked;
- benchmark overfitting remained blocked;
- a known ~15% serde_json improvement was reproduced in isolated worktrees;
- a known performance-neutral serde_json change was rejected.

## Required redesign before another pro test

Do not ship the current PerfForge design as a production skill.

A credible v2 needs at least:

1. **Claim-scoped workloads** — every performance claim declares which workload distribution, size regimes and latency/throughput dimensions it covers.
2. **Representative workload discovery** — repository benchmarks, issue/regression cases, production-like fixtures and adversarial boundary cases should be discovered before measuring the candidate.
3. **Precision-driven sampling** — sample until a preregistered confidence/precision target or budget is reached, rather than always stopping after nine samples.
4. **Cross-run stability** — require agreement across independent process groups/runners for near-threshold gains.
5. **Per-workload verdicts** — allow `IMPROVES workload A / REGRESSES workload B` rather than collapsing all performance into a universal faster/slower claim.
6. **No historical-label oracle** — historical commits can provide test cases, but their commit messages must not be treated as ground truth outside the workload they actually measured.

## Final scorecard

```text
Small test:                         PASS_SMALL
Ubuntu pro synthetic:              8/8 PASS
macOS pro synthetic:               7/8 FAIL
Synthetic false accepts:           0
macOS false reject:                near_25
serde_json known ~15% patch:       ACCEPT / correct
serde_json neutral patch:          REJECT / correct
Lodash historical patch:           REJECT vs preregistered ACCEPT
Real repository matrix:            2/3 FAIL
Runtime budgets:                   PASS
Acceptance criteria weakened:      NO
Workload changed after result:     NO
Overall binding verdict:           FAIL_PRO
Production promotion:              NO
```

## Engineering conclusion

PerfForge remains a promising direction, but the hard test found the exact two problems a performance-verification skill must solve before it can be trusted: noisy modest effects and workload dependence.

Do not merge or publish a PerfForge production skill from this experiment. A v2 should treat performance as a vector over declared workloads and use precision-driven measurement before another frozen evaluation.
