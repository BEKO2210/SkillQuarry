# Build Entropy Probe — Frozen Unseen Holdout Protocol

Status: **FROZEN before any holdout execution**

The historical gate in `FROZEN_PROTOCOL.md` was used to select the candidate. This second gate tests generalization on real nondeterminism fixes that were not present in that harness when the detector was selected.

## Detector — unchanged

The detector may not inspect source patterns, commit messages, container types, language APIs, or known fixes.

Its only signal is repeated observable output:

> same revision + same source inputs + same declared environment + repeated fresh executions -> SHA-256 digest set

A revision is flagged only when more than one output digest is observed.

## Frozen unseen cases

All three cases were selected before execution.

| Case | Broken revision | Repaired revision | Mechanical witness |
|---|---|---|---|
| `jplevyak/pyc` | `840178f52f64b7335fb6d86f00a55e70a0c5c766` | `03dad0b8aae0fde7105f4aa920724e6d090f5dd7` | generated `.c` for one fixed 10-field class source |
| `cajasmota/grafel` | `5941babb1f338156212d627e74808832447398a0` | `d7fb21b3e317a1592e0d05b56913238d68a94fc8` | `graph.json` from the issue-481 Lua + Markdown fixture |
| `JakeChampion/lang` | `9b24b15f252dd39a52dcdbbeedc88bb795268003` | `2426535e5c550ae8d8eb335ef6bf9008acf7c0f7` | `printer.Print` bytes from the fixed fan-out three-import project |

### Fixed inputs

- 25 executions per revision per case.
- `pyc`: build the historical compiler once per revision, then invoke that compiler as a fresh process 25 times on the same source path.
- `grafel`: inject the same untracked test harness into both revisions. It indexes the same issue-481 fixture 25 times with `SOURCE_DATE_EPOCH=1700000000` and saves every `graph.json`.
- `lang`: inject the same untracked external-package test harness into both revisions. It loads and prints the same fan-out project 25 times and saves every rendered Program.
- Harness files are never committed into the target repositories and are removed after the probe.

## Holdout recovery gate

A case is recovered only when:

1. broken revision: **>1 distinct SHA-256**, and
2. repaired revision: **exactly 1 distinct SHA-256**.

The candidate requires **at least 2 of 3 recovered cases**.

All three cases must execute cleanly. A dependency failure, build failure, timeout, missing witness, or target invocation error is `INFRA`, never a recovery or a miss.

A clean broken revision that produces one digest is a genuine `MISS`; the harness may not be redesigned after observing it.

## False-positive controls

The detector is also run on two current SkillQuarry generators, ten executions each, from an unchanged checkout:

1. `python3 tools/render_readme.py` — witness: `README.md` + `registry/skills.json`.
2. `python3 tools/build_site.py` — witness: the complete `site/` file tree, including relative paths and executable bits.

Required: **0 of 2 controls flagged** (one distinct digest per control).

A control command failure is `INFRA`, not a pass.

## Asymmetry gate

For every recovered holdout case, the runner preserves the first two byte-distinct witnesses from the broken revision.

- Discovery cost: median wall-clock time per candidate execution for that broken revision.
- Verification cost: median wall-clock time of 100 independent SHA-256 comparisons of the preserved witness pair.
- Per-case ratio: `verification_median / discovery_median`.

Required: **every recovered case <= 25%**.

The candidate dies if any recovered case exceeds the threshold.

## Resource budgets

- 45 minutes total CI job timeout.
- 25 executions per revision per holdout case; no adaptive extra runs.
- 10 executions per false-positive control.
- No LLM oracle.
- No target source modifications other than an untracked test harness whose full content is identical on broken and repaired revisions.

## Allowed post-run changes

Only invocation defects that prevent this exact frozen experiment from executing may be corrected: package installation, a wrong executable path, an API signature mismatch already present in both target revisions, or failure to create an output directory.

Forbidden after observing results:

- changing a holdout case or revision;
- changing the witness;
- changing source input content because a clean run failed to expose entropy;
- changing run counts or thresholds;
- adding seed perturbations not frozen above;
- converting a clean miss into `INFRA`.

## Decision

The candidate survives Phase 2 only if all of these are true:

- unseen recovery >= 2/3;
- infra cases = 0;
- false-positive controls flagged = 0/2;
- asymmetry gate passes for every recovered case.

Otherwise the candidate is rejected or, if infrastructure prevented execution, remains unresolved rather than being promoted.
