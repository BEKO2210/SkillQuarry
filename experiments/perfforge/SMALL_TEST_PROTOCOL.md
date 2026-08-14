# PerfForge Small Test Protocol

Date: 2026-08-15
Branch: `test/perfforge-small-20260815`
Base main: `1f04ad8864c50b634269117473c08de670368f7c`

## Hypothesis

A performance-agent protocol is materially stronger than a generic "measure before/after" workflow if it can distinguish genuine, behavior-preserving improvements from seductive benchmark wins caused by semantic breakage, memory tradeoffs, noise, regressions, or workload overfitting.

## Frozen cases

Eight cases are fixed before the first CI run.

Must ACCEPT:

1. `genuine_dedupe` — O(n^2)-style first-occurrence dedupe replaced by an order-preserving hash-backed implementation.
2. `genuine_aggregation` — repeated key scans replaced by one-pass dictionary aggregation.

Must REJECT:

3. `wrong_but_fast` — faster implementation changes first-occurrence ordering.
4. `hidden_edge_case` — common positive benchmark remains correct but negative inputs are semantically wrong.
5. `memory_for_speed` — correct closed-form calculation buys speed with an intentionally large per-call allocation.
6. `measurement_noise` — baseline and candidate are identical; noise must not become an optimization claim.
7. `true_regression` — behavior is preserved but extra work makes the candidate slower.
8. `benchmark_overfit` — large primary input improves, while small-request latency regresses severely.

## Frozen decision gate

The candidate is accepted only if all of the following are true:

1. every semantic probe matches baseline output and output type exactly;
2. primary workload 95% bootstrap lower bound for paired median speedup is >= 1.10 for wall time;
3. the same >= 1.10 lower bound holds for process CPU time;
4. no measured workload has candidate median wall time > 1.25x baseline;
5. peak traced per-call allocation is not more than 4 MiB above baseline.

Measurement configuration:

- 3 warmups per side;
- 13 randomized paired samples;
- 2,000 fixed-seed bootstrap resamples;
- deterministic random seed `0x5A17F0`;
- GC disabled during timing samples, enabled for semantic/memory checks;
- peak allocation measured separately with `tracemalloc`.

## Binding acceptance

`PASS_SMALL` requires:

- exact classification 8/8;
- both genuine improvements accepted;
- all six adversarial cases rejected;
- zero false accepts;
- zero false rejects;
- the same case-level verdicts on Ubuntu 24.04 and macOS.

Any threshold/case/expected label changed after observing a substantive benchmark result invalidates this protocol. Infrastructure-only fixes are allowed only if no benchmark classification has been observed and must be documented.

## Scope

This is a falsifiable small test of the proposed SkillQuarry extension, not production validation. Passing does not prove statistical optimality, cross-language portability, benchmark representativeness, or resistance to a malicious benchmark author.
