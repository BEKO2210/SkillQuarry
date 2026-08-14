# Experiments

What was tried, what it cost, and what it taught. A skill reaches `skills/`
only after passing a protocol frozen before the first substantive run. Four did.
Others did not, and their failures are kept here because a failed evaluation is
the cheapest thing this project owns.

Every experiment is preserved as a **tag**, not a branch: branches get cleaned up
after merges, and evidence that disappears is not evidence.

| Experiment | Verdict | Evidence | Outcome |
|---|---|---|---|
| RanGate | passed | `skills/security/rangate/` | published 1.0.0 |
| LockScope v2 | `PASS_V2` | tag `research/lockscope-v2` | published 1.0.0 |
| CrypticShift | failed final gate | removed on request | not published, removed entirely |
| PerfForge v1 | `FAIL_PRO` | tags `research/perfforge-v1`, `research/perfforge-small` | not published, kept as research |

---

## PerfForge v1 — `FAIL_PRO` (2026-08-15)

**Idea.** Judge whether a proposed patch is genuinely faster, and reject the
ways a patch can look faster without being faster.

**What worked.** The defences held, and they are the hard part:

```text
faster but wrong                 REJECT
~20% faster, +40-50 MB RSS       REJECT   (memory traded for speed)
~20% faster warm, 5.4x slower cold   REJECT   (cold-start trick)
~26% faster large, 2.07x slower small   REJECT   (benchmark overfitting)
serde_json +15% historical patch     ACCEPT   (median +15.9%, 95% LB +15.3%)
```

**Why it failed.** Two findings, both about the measurement rather than the
idea:

1. **Nine paired samples are not enough near the threshold.** On macOS a case
   that really was about 25% faster measured a 95% lower bound of 0.812x
   against a required 1.080x, and was rejected. One false reject, zero false
   accepts — the error landed on the safe side, but a gate that rejects real
   wins is not usable.
2. **"This patch is faster" is not a complete sentence.** The historical Lodash
   commit was about 10.7x *slower* on the workload frozen in advance, because
   that commit fixes a pathological whitespace case by replacing regex
   behaviour with a backwards scan. Both measurements are correct. A historical
   commit label is therefore not a universal performance oracle: faster for
   which workload, which input sizes, which metric?

**What a v2 would need.** Performance as a vector rather than a number — small
latency, large throughput, cold start, warm state, memory, allocations,
adversarial input, each judged separately — and sampling that continues until
the confidence interval is narrow enough to decide, instead of a fixed nine.

**Status.** Research. Not in `skills/`, not on the site, not in the registry.

---

## CrypticShift — removed (2026-08-14)

Strong synthetic numbers, no passing real-repository run: the corrected run was
killed by CI after 25 minutes against a frozen 20-minute limit, with a genuine
Rust test still executing. The deeper reason is worth keeping: its advantage was
consumed by the cost of verifying the candidates it produced.

Removed from the repository at the maintainer's request, including the
evaluation workflows and their run history.

---

## The rule these produced

A candidate is worth building when finding is expensive and **checking is
cheap**, and when something outside the tool — a compiler, a runtime, a
reproducible failure, a commit where a human fixed exactly this — can say
whether a finding is real. Both failures above violate one of those; both
published skills satisfy them.

That is what [SKILL-DISCOVERY.md](SKILL-DISCOVERY.md) asks a research model for.
