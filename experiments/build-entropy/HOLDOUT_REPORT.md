# Build Entropy Probe — Unseen Holdout Report

Status: **UNRESOLVED — not eligible for promotion**

This report records the frozen Phase 2 protocol without changing its decision rule.

## Frozen decision rule

Phase 2 required all of the following:

- unseen historical recovery >= 2/3;
- **all three cases execute cleanly** (`infra_cases = 0`);
- 0/2 false-positive controls flagged;
- verification/discovery ratio <= 25% for every recovered case.

Infrastructure failure was explicitly defined as unresolved, not as a detector miss and not as a pass.

## Final run

GitHub Actions run: `31855957595`

Head: `a20fbc9899caf89d3ebdee7aa22df080742c993e`

### Unseen recovery

| Case | Broken distinct digests | Fixed distinct digests | Result |
|---|---:|---:|---|
| `cajasmota/grafel` | 25 / 25 | 1 / 25 | RECOVERED |
| `JakeChampion/lang` | 4 / 25 | 1 / 25 | RECOVERED |
| `jplevyak/pyc` | not reached | not reached | INFRA |

Observed clean recoveries: **2/3**, which meets the numerical recovery threshold.

### False-positive controls

- `tools/render_readme.py`: 1 distinct digest across 10 executions.
- `tools/build_site.py`: 1 distinct digest across 10 executions.
- Controls flagged: **0/2**.

### Asymmetry

Recovered cases only, as frozen:

- `grafel`: discovery median `0.03860842 s`; verification median `0.000010416 s`; ratio `0.0002698` = **0.027%**.
- `lang`: discovery median `0.000100512 s`; verification median `0.000001072 s`; ratio `0.0106654` = **1.07%**.

Both are below the frozen 25% maximum.

## Why pyc remains INFRA

Three compatibility attempts were permitted only because they addressed invocation/build-environment failures rather than detector behavior:

1. Use the repository's documented Clang toolchain instead of GNU Make's built-in `g++` default.
2. Materialize the repository-declared generated `ifa/if1/check_cast.cc` target before the incomplete historical dependency graph builds `num.o`.
3. Pin Ubuntu 24.04 to Clang/LLVM 20, matching the project's later documented CI toolchain choice.

The final attempt still fails while compiling the pinned broken revision before the detector can execute:

```text
codegen/llvm.cc:83:30: error: no viable conversion from 'llvm::Triple' to 'StringRef'
TheModule->setTargetTriple(llvm::Triple(TargetTriple));
```

This is target-source/toolchain incompatibility. Fixing it would require patching the historical target source or changing the frozen case, both forbidden by `HOLDOUT_PROTOCOL.md` after results were observed.

Therefore `pyc` remains **INFRA**, not MISS and not RECOVERED.

## Decision

```text
recovered:                   2/3  PASS numerically
false-positive controls:     0/2  PASS
asymmetry:                         PASS
infra cases:                   1  FAIL promotion gate
---------------------------------------------------
PHASE 2:                   UNRESOLVED
```

Build Entropy Probe is **not promoted into `skills/`** from this experiment. The positive evidence is preserved, but the frozen protocol does not permit calling the candidate validated while one required holdout cannot execute.

No detector rule, witness definition, run count, case SHA, threshold, or false-positive control was changed after the holdout was frozen.
