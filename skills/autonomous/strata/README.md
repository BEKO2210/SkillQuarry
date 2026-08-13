<div align="center">

<img src="../../../assets/strata-banner.svg" alt="Strata — generational handoff runner for Claude Code" width="820">

<br>

**Every generation is a fresh context. Only a validated core sample crosses the boundary.**

[![Tests](https://img.shields.io/badge/tests-100%20passing-2ea043?style=for-the-badge)](TEST_REPORT.md)
[![Coverage](https://img.shields.io/badge/runner%20coverage-100%25-2ea043?style=for-the-badge)](TEST_REPORT.md)
[![Dependencies](https://img.shields.io/badge/dependencies-none-5b8298?style=for-the-badge)](#install)
[![Python](https://img.shields.io/badge/python-3.10%2B-3d5568?style=for-the-badge&logo=python&logoColor=white)](pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache--2.0-f0932b?style=for-the-badge)](../../../LICENSE)

[**Install**](#install) ·
[**Use**](#use) ·
[**How it works**](#how-it-works) ·
[**Safety**](#safety-model) ·
[**Reference**](#command-reference) ·
[**Evidence**](TEST_REPORT.md)

</div>

---

## What it is

Strata runs a long coding task as a series of **generations**. Each generation is
its own `claude -p` process with an empty conversation history. Before it ends, it
must return a schema-validated handoff — the *core sample*. Strata persists that
handoff atomically and injects it into the next fresh process.

A conventional agent loop re-feeds one growing conversation. Strata never does:

```text
   Conventional loop                 Strata
   ─────────────────                 ──────
   run 1  ▏ctx ██                    gen 1  ▏ctx ██   →  handoff  ▏█
   run 2  ▏ctx ████                  gen 2  ▏ctx ██   →  handoff  ▏█
   run 3  ▏ctx ███████               gen 3  ▏ctx ██   →  handoff  ▏█
   run 4  ▏ctx ██████████            gen 4  ▏ctx ██   →  complete
```

The rule every generation is told:

> **Store a fact only when preserving it is cheaper than rediscovering it.**

## Install

No packages, no network, no build step. Python 3.10+ and git are the only requirements.

```bash
cd skills/autonomous/strata
./install.sh          # installs `strata` into ~/.local/bin
strata --version
```

`STRATA_PREFIX=/somewhere/else ./install.sh` changes the target. `./uninstall.sh`
removes exactly what was installed. For packaging environments, `pip install -e .`
also works.

## Use

Start from a clean git repository:

```bash
strata start "Fix the repository so lint and build pass without weakening checks." \
  --verify "npm run lint" \
  --verify "npm run build" \
  --max-generations 20 \
  --max-budget-usd 3
```

Resume after a crash, a closed terminal, or a dead host:

```bash
strata resume
```

Inspect without spending anything:

```bash
strata status     # phase, generation, last validated handoff
strata metrics    # real token/cost telemetry reported by Claude Code
```

Step through one generation at a time:

```bash
strata start "..." --one-generation
strata resume --one-generation
```

## How it works

```text
                    ┌──────────────────────────────┐
   master task ────▶│  generation N                │
   last handoff ───▶│  fresh `claude -p` process   │
   git status ─────▶│  works, tests, decides       │
                    └───────────────┬──────────────┘
                                    │ structured handoff (JSON Schema)
                                    ▼
                       validate → compact → fsync → atomic replace
                                    │
                    status=complete ├────────▶ independent verification
                                    │              │           │
                                    │            PASS        FAIL
                                    │              │           │
                    status=continue │           finish   failure handoff
                                    ▼                          │
                            next fresh generation ◀────────────┘
```

**The handoff** carries: status, summary, completed work, decisions, failed
approaches, changed files, `read_first`, the exact next action, tests, blockers
and completion evidence. Never the previous transcript.

**Completion is not a claim.** When a generation reports `complete`, every
`--verify` command runs as an independent process. A single failure overrules the
agent: Strata rewrites the handoff into a `continue` carrying the exact failing
output, and the next generation starts from that.

**State lives in `.strata/`** and is registered in `.git/info/exclude`, so the
user's `.gitignore` is never touched. `state.json` is the single source of truth
(temp file → `fsync` → atomic replace); `history.jsonl` is diagnostic only and is
never fed back to the model.

## Safety model

| Guard | Behaviour |
|---|---|
| Dirty repository | Refused unless `--allow-dirty` is passed explicitly |
| Destructive git | Never performed by the runner; the prompt forbids it too |
| Concurrent runners | `flock` on `.strata/run.lock`, second runner refused |
| Crash mid-generation | Next generation is told its predecessor's conclusions are untrusted, and gets live git status/diff stat instead |
| False `complete` | Independent `--verify` commands overrule the agent |
| No-progress loop | Identical handoff fingerprint 3× ends the run |
| Runaway spend | `--max-generations`, `--max-turns`, `--timeout`, `--max-budget-usd` |
| Context blowup | Hard 16 KB handoff budget with deterministic tiered compaction |
| Mutated task | Task hash is pinned in state; a changed task refuses to resume |
| Session leakage | Every generation runs with `--no-session-persistence` |

Two behaviours worth knowing before the first run:

- **Permission mode defaults to `acceptEdits`.** Claude Code's `auto` mode denies
  every write when running headless, so a loop under `auto` burns generations
  without touching the repository. Measured, see [TEST_REPORT.md](TEST_REPORT.md).
- **`--verify` commands are not shell commands** by default; they are split with
  `shlex` and executed directly. Pass `--verify-shell` when a check needs pipes
  or `&&`.

## Command reference

```text
strata start <task> [options]     initialize and run a new generational loop
strata resume [--one-generation]  continue or recover from persisted state
strata status                     print phase, generation and last handoff
strata metrics                    aggregate token/cost telemetry
strata reset                      delete only .strata/ runner state
```

| Option | Default | Purpose |
|---|---|---|
| `--verify CMD` | — | Independent completion check (repeatable) |
| `--verify-shell` | off | Run checks through the shell |
| `--max-generations N` | 20 | Hard ceiling on generations |
| `--max-turns N` | 24 | Turn cap per generation |
| `--timeout S` | 1800 | Per-generation wall clock, process group killed on expiry |
| `--max-budget-usd X` | — | Stops the run instead of retrying |
| `--stall-limit N` | 3 | Identical handoffs before the run is stopped |
| `--turn-limit-strikes N` | 3 | Turn-capped generations in a row before stopping |
| `--max-handoff-bytes N` | 16000 | Hard handoff budget |
| `--model` / `--effort` | — | Passed through to Claude Code |
| `--permission-mode` | `acceptEdits` | Claude Code permission mode |
| `--claude-arg ARG` | — | Extra Claude Code argument (repeatable) |
| `--allow-dirty` | off | Permit starting on a dirty tree |
| `--one-generation` | off | Run exactly one generation and stop |

Exit codes: `0` complete or cleanly paused · `2` refused/error · `3` stopped
without completion (blocked, stalled, ceiling reached) · `130` interrupted.

## Tests

```bash
python3 tests/run_tests.py            # 100 tests + coverage report
python3 tests/run_tests.py --min 100  # fails below 100% line coverage
```

The suite drives a fake `claude` binary that honours the real command contract, so
git repositories, subprocesses, locks, crash states and verification are all real.
Results and the live Claude Code runs are documented in
[TEST_REPORT.md](TEST_REPORT.md).

## Credits

Strata implements the generational variant of the *Ralph Wiggum* agent-loop
technique: instead of looping inside one session, it deliberately ends the context
and carries a validated handoff forward. Part of
[SkillQuarry](../../../README.md).
