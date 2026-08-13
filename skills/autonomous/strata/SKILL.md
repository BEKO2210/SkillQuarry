---
name: strata
description: Use when a coding task is too large for one agent session and must survive context loss, crashes and false completion claims — long refactors, migrations, "make the build green", multi-file features. Runs the task as a series of fresh Claude Code processes that hand a validated core sample of engineering memory to their successor, and lets independent verification commands overrule the agent's own completion claim. Trigger phrases include "run this until it passes", "long-running task", "autonomous loop", "ralph loop", "fresh context each iteration", "resume after crash", "verify before declaring done".
---

# Strata — generational handoff runner

Strata turns one long task into a chain of short generations. Every generation is
a separate `claude -p` process with an empty context; the only thing crossing the
boundary is a schema-validated handoff.

Use it when the work is longer than one comfortable session, when a run must
survive a crash or a closed laptop, or when "done" must be proven by commands
rather than claimed by a model. Do not use it for a task a single session finishes
comfortably — the per-generation prompt overhead is not worth it.

## Before starting a run

1. **Commit or stash everything.** Strata refuses a dirty tree unless
   `--allow-dirty` is passed, so existing work is never confused with its own.
2. **Write the master task as an outcome, not a procedure.** It is hashed and
   immutable for the whole run; changing it later makes `resume` refuse.
3. **Decide what proves completion**, and pass each proof as `--verify`. Without a
   verifier, the agent's own `complete` claim is accepted unchecked. This is the
   single highest-value argument.
4. **Set a ceiling.** `--max-generations` and, when spending real money,
   `--max-budget-usd`.

## Running

```bash
strata start "<outcome-shaped master task>" \
  --verify "<check that must exit 0>" \
  --max-generations 20 \
  --max-budget-usd 3
```

- `strata status` — phase, generation, last validated handoff. Free.
- `strata metrics` — real token and cost telemetry from Claude Code. Free.
- `strata resume` — continue after any interruption, including a killed host.
- `strata reset` — delete `.strata/` only; never touches repository files.
- `--one-generation` — run exactly one generation, for stepping through a run.

## Reading the outcome

| Phase | Meaning | Next move |
|---|---|---|
| `complete` | Handoff said complete **and** every verifier exited 0 | Review the diff, commit |
| `verification_failed` | Agent claimed done, a verifier disagreed | Usually self-heals next generation; if it repeats, the verifier or the task is wrong |
| `blocked` | Agent reported a blocker it cannot pass | Read `blockers` in `strata status`, remove the obstacle, `strata resume` |
| `stalled` | Identical handoff repeated; no progress | The task is under-specified or the agent lacks a tool. Reword and start a new run |
| `turn_limit` | Generations keep hitting `--max-turns` | Raise it or split the task |
| `max_generations` | Ceiling reached without completion | Inspect the diff, then resume with a higher ceiling if progress is real |
| `budget_exhausted` | Cost ceiling reached | Raise `--max-budget-usd` and resume |

Exit codes: `0` complete or cleanly paused, `2` refused/error, `3` stopped without
completion, `130` interrupted.

## Rules that matter

- **Never weaken a verifier to make a run finish.** The verifier is the only thing
  standing between a claim and the truth.
- **Never edit `.strata/state.json` by hand.** It is the canonical memory and is
  integrity-checked; edit the repository instead and let the next generation see it.
- **`--verify` is not a shell** unless `--verify-shell` is passed. `a && b` needs
  that flag.
- **Do not switch the permission mode to `auto`** for headless runs: Claude Code
  denies every write in that mode and the loop makes no changes at all.
- **Read `strata status` before resuming a run you did not start.** The last
  handoff explains where the previous generation stopped and what it already ruled out.

## Files

| Path | Purpose |
|---|---|
| `.strata/state.json` | Canonical state and the last validated handoff |
| `.strata/config.json` | Immutable run configuration |
| `.strata/history.jsonl` | Diagnostic log, never fed back to the model |
| `.strata/last-prompt.txt` | Exact prompt of the most recent generation |
| `.strata/last-claude.json` | Raw Claude Code response envelope |
| `.strata/last-verification.json` | Result of the most recent verification pass |

`.strata/` is added to `.git/info/exclude`, so the repository's `.gitignore` stays untouched.

Full documentation: `README.md`. Verified behaviour and known limits: `TEST_REPORT.md`.
