<div align="center">

<img src="../../../assets/cordon-logo.svg" width="96" alt="Cordon logo">

# Cordon

### Deterministic Git change envelopes for coding agents

**Limit the blast radius. Verify the result. Trust evidence, not the completion claim.**

<img src="../../../assets/cordon-banner.svg" width="780" alt="Cordon — arm, agent, audit, accept or reject">

[![Status](https://img.shields.io/badge/status-tested-2ea043?style=for-the-badge)](TEST_REPORT.md)
[![Tests](https://img.shields.io/badge/tests-57%20passing-2ea043?style=for-the-badge)](TEST_REPORT.md)
[![Coverage](https://img.shields.io/badge/core%20coverage-100%25-2ea043?style=for-the-badge)](TEST_REPORT.md)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache--2.0-5b8298?style=for-the-badge)](../../../LICENSE)

</div>

---

## Why Cordon exists

Agent permissions answer what an agent is allowed to attempt. Cordon answers a
separate question after the work has happened:

> **Did the Git-visible result stay inside the exact change envelope I armed, and do my independent checks pass?**

Cordon snapshots `HEAD`, stores a path policy and numerical budgets, then audits
the working tree relative to that baseline. A model saying “done” has no special
weight: a path violation or failing verifier rejects the result.

Cordon complements **[Strata](../../autonomous/strata/)**. Strata keeps long work
moving across fresh Claude contexts; Cordon bounds and verifies the resulting
Git-visible change set.

## Install

Requirements: Python 3.10+ and Git. No `pip`, virtual environment or third-party
Python package is used.

```bash
cd skills/security/cordon
./install.sh
cordon --version
```

Default install prefix is `$HOME/.local`. Override without elevated privileges:

```bash
CORDON_PREFIX="$HOME/tools" ./install.sh
```

The installer writes a content-addressed release directory first and atomically
replaces the launcher last. Reinstalling identical source reuses the same release.

Uninstall:

```bash
./uninstall.sh
```

Uninstall removes program files only. It deliberately does not search for or
delete `.cordon/` state inside repositories.

## Fast start — any coding agent

Start from a clean Git worktree:

```bash
cordon arm "change only the parser and its tests" \
  --allow "src/parser/**" \
  --allow "tests/parser/**" \
  --deny "src/parser/generated/**" \
  --max-files 8 \
  --max-added-lines 400 \
  --max-deleted-lines 200 \
  --max-working-bytes 250000 \
  --max-binary-files 0 \
  --verify "python3 -m unittest discover -s tests"
```

Run your preferred agent normally, then:

```bash
cordon check
```

Cordon prints JSON containing the baseline/current HEAD, changed paths, measured
budgets, violations and verifier results. Exit `0` means accepted; exit `3` means
rejected.

## Claude Code mode

Cordon can also own one Claude Code attempt:

```bash
cordon run "Fix the parser regression. Keep generated files untouched." \
  --allow "src/parser/**" \
  --allow "tests/parser/**" \
  --deny "src/parser/generated/**" \
  --verify "python3 -m unittest discover -s tests" \
  --max-files 8 \
  --max-added-lines 400 \
  --max-turns 20 \
  --max-budget-usd 2
```

The exact Claude flags Cordon emits are documented against Anthropic's primary
CLI reference in `RESEARCH.md`. It uses `--permission-mode acceptEdits`, not
`auto`, following the measured Strata reference finding supplied with this repo.

If the Claude process fails or a verifier rejects the partial result:

```bash
cordon status
cordon resume
```

Resume starts a **fresh** Claude process. It refuses to continue if the current
partial Git-visible changes already violate the armed envelope or if the maximum
attempt count has been reached.

## Envelope model

### Path policy

Cordon's globs are intentionally small and explicit:

| Pattern | Meaning |
|---|---|
| `src/*` | one component directly below `src/` |
| `src/**` | anything below `src/`, crossing `/` boundaries |
| `**/test?.py` | test filename at root or below directories; `?` is one non-slash character |

Deny patterns are evaluated first and win.

### Numerical budgets

Defaults:

| Budget | Default |
|---|---:|
| changed files | 25 |
| added lines | 2,000 |
| deleted lines | 1,000 |
| current working bytes | 2 MiB |
| binary files | 2 |
| Claude attempts | 3 |

A budget is inclusive. Tests prove the exact boundary and one-byte/one-line over
cases. Non-ignored untracked files are preflighted by metadata first; Cordon has
a hard 64 MiB total untracked scan ceiling. The streaming reader enforces the
remaining budget again while reading, so growth after metadata preflight is also
rejected after at most one detection byte beyond the budget.

### Commit movement

By default, a changed `HEAD` is a violation. If the task explicitly includes
committing, pass `--allow-commits`. The diff is still evaluated from the original
armed commit, so committed changes do not disappear from the audit.

## Verifiers

Each `--verify` string is tokenized with Python `shlex.split` and executed as a
process directly. Cordon does not invoke a shell for verifier strings.

Good:

```bash
--verify "python3 -m unittest discover -s tests"
--verify "git diff --check"
```

Not equivalent to shell syntax:

```bash
--verify "test-a && test-b"
```

That is parsed as literal arguments, not as `&&`. If a workflow needs shell
composition, put it in a reviewed script and verify that script directly.

Verifier timeouts, output-limit failures and non-zero exits all reject the audit.
At most 8 verifier commands are accepted, each command is capped at 4,096
characters, and only the first 16 KiB of each successful verifier stdout/stderr
stream is retained in persistent evidence (with an explicit truncation marker).
Policy rejection short-circuits verification, so commands do not run after the
change envelope is already known to be broken.

## Crash and process handling

Cordon state writes use a temporary file, flush, `fsync`, `os.replace`, then a
best-effort-supported directory `fsync`. On POSIX, managed children start in a
new session. Timeout or output overflow terminates the process group with TERM
and escalates to KILL after a grace period.

A zero-length synchronization inode resolved through Git metadata (`cordon.lock`)
is held with an OS advisory lock. `run` holds that same lock continuously across
arm/setup and the wrapped agent attempt, so a second Cordon mutation cannot enter
mid-run. The lock inode contains no semantic state and is deliberately never
replaced while locked. Interrupted Claude attempts are persisted as `interrupted`.
Engine failures are persisted as `engine_error`. A follow-up `resume` sees the
previous audit/error and receives recovery context.

## State

`.cordon/` contains the local run state. The directory is added to
`.git/info/exclude` as `/.cordon/`; `.gitignore` is never modified.

Useful commands:

```bash
cordon status
cordon check
cordon resume
cordon reset
```

`cordon reset` removes only `.cordon/` and never reverts source changes.

## Security boundary — read this

Cordon is an **acceptance/audit layer**, not an OS sandbox.

Version 1 intentionally sees:

- tracked changes relative to the armed commit;
- non-ignored untracked files returned by Git.

It does not claim visibility into files Git excludes through `.gitignore`,
`.git/info/exclude`, global excludes or other standard ignore sources.

Tracked files carrying the `assume-unchanged` or `skip-worktree` index flag are
invisible to `git diff`, so Cordon refuses to arm while such a flag exists and
counts any flag that appears afterwards as a violation — a blind spot is never
reported as a clean result. A write
through a repository symlink to a target outside the repository is likewise outside
the target repository's Git-visible evidence. A malicious process with unrestricted filesystem write access can also rewrite `.cordon`
state and its hashes. If hostile-code containment is the requirement, use an
appropriate OS/container/VM boundary in addition to Cordon.

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | accepted or non-error informational action |
| 2 | invalid policy/state/repository operation |
| 3 | audit rejected |
| 4 | wrapped Claude process error, timeout or output overflow |

## Tests

```bash
cd skills/security/cordon
python3 tests/run_tests.py --min 100
```

Recorded build result: **57 tests passing; core.py 100.0% (962/962 executable
lines)** on Python 3.13.5 / Git 2.47.3 / Linux 6.18.35. No authenticated Claude
binary was available in this sandbox; Claude integration is simulated by a fake
binary with the same Cordon-used command-line contract. See `TEST_REPORT.md` and
`REVIEW.md` for the exact limitations and target-machine probes.

## Research and review evidence

- `RESEARCH.md` — primary sources, market scan, open uncertainties.
- `CANDIDATES.md` — three evaluated skill candidates and selection rationale.
- `TEST_REPORT.md` — reproducible test evidence and defects found/fixed.
- `REVIEW.md` — short verification map for the second agent.

## License

Apache License 2.0, matching SkillQuarry.
