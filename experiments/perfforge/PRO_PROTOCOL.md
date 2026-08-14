# PerfForge Pro Evaluation Protocol

Date frozen: 2026-08-15
Branch: `test/perfforge-pro-20260815`
Small-test evidence: `PASS_SMALL`, workflow `31848014924`

## Question

Can a performance-claim gate distinguish real improvements from small/noisy effects, semantic cheating, cold-start regressions, memory-for-speed trades and benchmark overfitting, and can it reproduce the direction of known real-world performance commits in isolated Git worktrees?

This evaluates the gate, not an optimizer. A passing result does not mean PerfForge can discover optimizations by itself.

## Frozen statistical gate

- baseline and candidate execute in separate processes;
- real repositories use separate Git worktrees at the direct parent and candidate commit;
- AB/BA execution order is randomized with fixed seed `0x50465247`;
- synthetic warm measurements: 9 paired samples, chunked into three independent process pairs;
- synthetic cold measurements: 3 fresh process pairs;
- 2,000 fixed-seed paired bootstrap resamples on log speed ratios;
- primary lower 95% speedup bound must be `>= 1.08`;
- no workload median may regress by more than `1.20x`;
- cold-start median may not regress by more than `1.25x`;
- synthetic candidate RSS may not increase by more than 32 MiB;
- semantic digests must be identical.

A faster patch that breaks any hard gate is `REJECT`.

## Synthetic matrix — binding 8/8

Expected ACCEPT:

1. `near_14`: about 14% less redundant CPU work, same result.
2. `near_25`: about 25% less redundant CPU work, same result.

Expected REJECT:

3. `near_5`: a real but deliberately sub-threshold ~5% gain.
4. `wrong_but_fast`: faster but changes the semantic digest.
5. `memory_for_speed`: faster but keeps an extra 48 MiB allocation alive.
6. `cold_warm_tradeoff`: warm path faster but expensive setup makes fresh-process latency regress.
7. `benchmark_overfit`: primary large workload faster while small requests regress badly.
8. `identical_noise`: same implementation with deterministic sample-dependent timing perturbation.

Binding synthetic pass requires exact classification on Ubuntu 24.04 and macOS, zero false accepts and zero false rejects.

## Real repository matrix — binding 3/3

### serde-rs/json — known +15% String parsing optimization

Candidate: `86d0e114e1370deb0b00cc97f5aec8c3869d835e`
Commit message reports roughly +15% when parsing unicode escapes into `String`.

Expected: `ACCEPT`.

Proofs:
- direct parent vs candidate in separate Git worktrees;
- both repository library test suites pass;
- same unicode-escape workload and semantic digest;
- 11 independent process samples after two warmups;
- lower 95% speedup bound >= 1.08.

### lodash — large-string trim performance/security fix

Candidate: `c4847ebe7d14540bb28a8b932a9ce1b9ecbfee1a`

Expected: `ACCEPT`.

Proofs:
- direct parent vs candidate in separate worktrees;
- public `trim`, `trimEnd`, and `toNumber` semantic probe outputs match;
- large whitespace-string trim benchmark;
- 11 independent process samples after two warmups;
- lower 95% speedup bound >= 1.08.

### serde-rs/json — explicitly performance-neutral refactor

Candidate: `236cc8247d32a5cb337850d75f68265fdb4bc14e`
Commit message explicitly says the change does not affect performance.

Expected: `REJECT` as an optimization claim.

The same unicode workload, worktree isolation, tests and 1.08 lower-bound gate are used. If CI noise makes an 8% speedup statistically proven, the preregistered test fails rather than relabeling the case.

## Runtime budgets

- synthetic job: < 360 seconds per operating system;
- real-repository job: < 900 seconds.

Missing network/toolchain is `BLOCKED`, not evidence for or against the method. Once candidate evaluation begins, semantic or statistical failure is binding.

## Integrity rules

After the first substantive CI run:

- no expected label may change;
- no threshold may weaken;
- no benchmark workload may be replaced because of an unfavorable result;
- infrastructure-only fixes are allowed only when no candidate result was obtained, and must be recorded;
- every failed run remains part of the report.

## Binding verdict

`PASS_PRO` requires:

- synthetic 8/8 on Ubuntu;
- synthetic 8/8 on macOS;
- real repository 3/3;
- zero false accepts;
- all runtime budgets pass.

Anything less is `FAIL_PRO` or `BLOCKED` according to the rules above.
