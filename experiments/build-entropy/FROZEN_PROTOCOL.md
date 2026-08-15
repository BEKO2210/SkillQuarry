# Build Entropy Probe — Frozen Historical Protocol

Status: **FROZEN before execution**

This experiment tests whether repeated execution can expose build/generator nondeterminism that is invisible in a single successful run.

## Oracle

The detector is not allowed to inspect source patterns such as `set()`, `HashMap`, `map`, or unordered-container APIs.

Its only oracle is observable output:

> same repository revision + same source inputs + repeated fresh generator/build executions -> output digest set

A historical bug is recovered only when:

- the broken revision produces **more than one distinct digest**, and
- the repaired revision produces **exactly one distinct digest**,
- under the same case harness and repetition budget.

Process entropy may be deliberately varied when it is part of the runtime's normal nondeterministic behavior (for example Python hash seeding). The seed schedule is fixed here and is identical in shape for broken and repaired revisions.

## Frozen cases

| Case | Broken revision | Repaired revision | Witness |
|---|---|---|---|
| `cvc5/cvc5` | `38912c71996affb29683b9f7caa25ad574afacee` | `61602d09095f70ef6381a035a41b6d6a47c5d325` | generated `options_public.cpp` |
| `project-dalec/dalec` | `e0964d3e9f2e199f31331c7eb3ae9839f0153f33` | `ea705b3b3a52467fd2ffbdc08f3fa2ec289483f4` | marshaled BuildKit LLB `Def` bytes |
| `QQSHI13/min-html` | `3e384a90f841facebcfc9faeae0ace03f2cecf4a` | `2f65441ecefaa5d6411c7cb3658642c776e65c3f` | generated `attrs.rs` + `entities.rs` |

## Repetition budget

- **25 executions per revision per case**.
- cvc5 uses the fixed `PYTHONHASHSEED` schedule `1000..1024` to expose process-seeded set iteration reproducibly.
- Dalec rebuilds the LLB state from fresh maps 25 times in one Go test process. The same untracked test harness is injected into both revisions; product files are not changed.
- min-html compiles the historical build script once per revision, then directly executes that exact build-script binary 25 times into fresh `OUT_DIR` directories. This isolates generator entropy from dependency compilation noise.

## Gate

The candidate survives this historical gate only if **at least 2 of 3 cases are recovered**.

No partial credit:

- a broken-revision witness without disappearance on the repair is not recovery;
- a command failure, dependency failure, timeout, or missing artifact is `INFRA`, never a witness;
- pre-existing test failures are not detector success;
- no threshold or case may be changed after results are observed.

## Allowed post-run changes

After the first execution, only harness defects may be corrected: wrong paths, missing output directories, invocation mistakes, or equivalent errors that prevent the frozen experiment from running as specified.

Changing the oracle, case set, repetition count, pass threshold, or witness definition after seeing the result is forbidden.

## Non-claims

A pass does **not** claim that every nondeterministic build is detectable in 25 executions, that identical hashes prove semantic reproducibility, or that the detector identifies root cause. It only establishes that repeated-output entropy is a useful mechanical signal on the frozen historical set.
