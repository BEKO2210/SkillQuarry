# PerfForge Small Test Report

Date: 2026-08-15
Branch: `test/perfforge-small-20260815`
Base main: `1f04ad8864c50b634269117473c08de670368f7c`
Frozen protocol commit: `671a2433eddeebfcb73bab5228bae90395230471`
Workflow commit: `3740e9e5768891b878c6a61c70001532a03cb5da`
Passing workflow run: `31848014924`

## Verdict

**PASS_SMALL**

Both Ubuntu 24.04 and macOS produced the exact preregistered 8/8 classification:

- genuine improvements accepted: 2/2;
- adversarial/non-improvements rejected: 6/6;
- false accepts: 0;
- false rejects: 0.

No threshold, case, expected label, or benchmark implementation was changed after the first substantive run. The first CI run passed on both operating systems.

## What was tested

The experiment tests the proposed SkillQuarry extension of a measure-first performance workflow: an optimization claim is allowed only when semantic equivalence, statistically separated timing, workload regression limits, and a memory budget all agree.

Frozen gate:

- semantic probes: exact output + output type;
- 3 warmups;
- 13 randomized paired samples;
- 2,000 fixed-seed bootstrap resamples;
- primary wall-time lower 95% speedup bound >= 1.10;
- primary process-CPU lower 95% speedup bound >= 1.10;
- no workload median regression > 1.25x;
- peak traced allocation increase <= 4 MiB.

## Ubuntu 24.04

Python: 3.13.15
Runtime: 4.240 s

| Case | Expected | Result | Important evidence |
|---|---|---|---|
| genuine_dedupe | ACCEPT | ACCEPT | wall speedup median 214.54x; lower bound 209.38x |
| genuine_aggregation | ACCEPT | ACCEPT | wall speedup median 95.22x; lower bound 94.49x |
| wrong_but_fast | REJECT | REJECT | 3.42x faster but semantic probes failed |
| hidden_edge_case | REJECT | REJECT | 1.25x faster on common positives but negative-input semantics failed |
| memory_for_speed | REJECT | REJECT | 11.49x faster but +15,999,748 peak bytes |
| measurement_noise | REJECT | REJECT | identical implementation; lower bound 0.992x |
| true_regression | REJECT | REJECT | candidate 1.714x slower |
| benchmark_overfit | REJECT | REJECT | large input ~207.97x faster; small latency ~391.83x slower |

## macOS

Python: 3.13.14 arm64
Runtime: 3.510 s

| Case | Expected | Result | Important evidence |
|---|---|---|---|
| genuine_dedupe | ACCEPT | ACCEPT | wall speedup median 192.38x; lower bound 177.01x |
| genuine_aggregation | ACCEPT | ACCEPT | wall speedup median 99.56x; lower bound 98.76x |
| wrong_but_fast | REJECT | REJECT | 5.64x faster but semantic probes failed |
| hidden_edge_case | REJECT | REJECT | 1.37x faster on common positives but negative-input semantics failed |
| memory_for_speed | REJECT | REJECT | 11.70x faster but +15,999,748 peak bytes |
| measurement_noise | REJECT | REJECT | identical implementation; lower bound 0.952x |
| true_regression | REJECT | REJECT | candidate 1.777x slower |
| benchmark_overfit | REJECT | REJECT | large input ~183.83x faster; small latency ~373.68x slower |

## Strongest observations

### A fast wrong answer is still a failure

`wrong_but_fast` was materially faster on both machines. PerfForge rejected it because first-occurrence ordering changed.

### Memory is part of performance correctness

`memory_for_speed` produced the correct numerical answer and was more than 11x faster on both machines, but allocated roughly 16 MiB extra per invocation. The memory gate rejected it.

### One benchmark is not a workload

`benchmark_overfit` looked spectacular if only the primary large input was considered: around 208x faster on Linux and 184x faster on macOS. The same candidate made the small-request workload hundreds of times slower, so the multi-workload regression gate rejected it.

### Noise did not become evidence

The identical baseline/candidate case stayed below the preregistered 1.10 lower-bound gate on both machines and was rejected.

## Upstream relationship

The conceptual starting point is Addy Osmani's MIT-licensed `performance-optimization` agent skill, whose workflow is measure -> identify -> fix -> verify -> guard. This experiment does not copy that skill into SkillQuarry. It tests a proposed stronger mechanism: paired measurements plus statistical, semantic, memory, and workload gates before an agent may claim an optimization.

If a production derivative later incorporates upstream text or other copyrightable material, preserve the MIT copyright/license notice and document provenance.

## Limitations

This is deliberately a small falsification test, not production validation.

It does **not** yet prove:

- robustness for near-threshold 5-20% improvements;
- resistance to CI frequency scaling / noisy-neighbor effects;
- correctness of memory measurement for native processes or child processes;
- Rust/C++/Node/browser benchmark integration;
- benchmark representativeness discovery;
- protection against malicious benchmarks or benchmark-specific code paths;
- real-repository agent-generated optimization patches.

The accepted examples have intentionally large algorithmic wins. A production-strength evaluation must focus on much smaller effects, independent benchmark processes, real repositories, cold/warm behavior, and baseline-vs-candidate worktree isolation.

## Engineering decision

```text
Concept:                    PROMISING
Frozen small test:          PASS_SMALL
Cross-platform verdict:     PASS
False accepts:              0
False rejects:              0
Production skill:           NOT YET
Next step:                  HARD PRO TEST
```
