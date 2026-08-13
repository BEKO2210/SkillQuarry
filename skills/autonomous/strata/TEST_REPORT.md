# Test Report — Strata 1.0.0

Date: 2026-08-13

| | |
|---|---|
| Claude Code | 2.1.231 |
| Python | 3.12.3 |
| Platform | Linux 6.8 (x86_64) |
| Automated tests | **100 passed, 0 failed** |
| Line coverage of `runner.py` | **100%** (751/751; 5 lines excluded by pragma: Windows-only branches and the `__main__` guard) |
| Live Claude Code runs | 4 (model `haiku`), total reported cost **$0.269** |

Reproduce with:

```bash
python3 tests/run_tests.py --min 100
```

---

## 1. Live runs against real Claude Code

These are real API calls, not simulations. Cost and token figures come from
Claude Code's own JSON envelope and are stored in `.strata/history.jsonl`.

| # | Scenario | Result |
|---|---|---|
| 1 | Task "create `answer.txt` containing 42", one `--verify` command | `phase=complete generation=1`, file written, verifier exited 0, cost $0.081949 |
| 2 | Same shape with `--permission-mode auto` | **Every write denied**, no file created, `phase=blocked` — see finding B |
| 3 | Task "create a Keep-a-Changelog `CHANGELOG.md`" on the shipped build | `phase=complete generation=1`, verifier exited 0, cost $0.069413 |
| 4 | Two-generation handoff across **two separate OS processes** | Generation 1 wrote `calc.py` and handed off; a second `strata resume` process wrote `test_calc.py` from that handoff alone; the generated suite runs 5 tests and passes. Cost $0.117875 |

Run 4 is the load-bearing one: generation 2's prompt contained the previous
generation's structured handoff (`next_action: "Gen 2: Create test_calc.py …"`,
`decisions`, `changed_files`) and **not** generation 1's transcript.

Claude Code contract flags used by the runner were verified against
`claude --help` on 2.1.231: `--json-schema`, `--output-format json`,
`--no-session-persistence`, `--permission-mode`, `--max-budget-usd`, `--model`,
`--effort`. `--max-turns` is undocumented in `--help` but is honoured — a run with
`--max-turns 1` aborted with `subtype: error_max_turns`, exit code 1, and no
`structured_output`.

## 2. Five user-level scenarios (automated)

| Level | Scenario | Result |
|---|---|---|
| 1 — Beginner | Single generation reports complete, independent verifier exits 0 | PASS |
| 2 — Everyday developer | Generation 2 receives summary, decisions, `read_first` and next action; never the previous prompt | PASS |
| 3 — Advanced | Process killed mid-generation with a partial edit on disk; the successor is told the interrupted conclusions are untrusted and gets live git status | PASS |
| 4 — Expert | Agent claims COMPLETE too early; the verifier fails; Strata vetoes, rewrites the handoff with the exact failure, and only the repaired generation completes | PASS |
| 5 — Adversarial | Agent repeats an identical no-progress handoff; the stall detector stops after 3 instead of consuming all 10 generations | PASS |

Additional loop-control scenarios: hard `max_generations` ceiling, immediate stop
on `blocked`, single-generation mode for every exit path, three consecutive engine
failures aborting, transient failure retried with a recovery note.

## 3. Robustness and failure-mode coverage

- **Handoff validation** — missing `structured_output`, missing required fields,
  wrong types, mixed-type lists, invalid status, and the per-status evidence rules
  (`continue` needs a next action, `complete` needs evidence, `blocked` needs a blocker).
- **Compaction** — worst-case schema-maximal handoff plus 500 randomized handoffs,
  all forced under the 16,000-byte budget; an impossible budget raises instead of
  silently overflowing.
- **Engine error classification** — turn limit, budget stop, other subtypes,
  non-JSON output, `stop_reason` fallback.
- **Persistence** — corrupted JSON, non-object JSON, foreign schema version,
  unknown future keys, mutated master task, numeric limit tampering, reset idempotence.
- **Locking** — a second runner is refused while the first holds the lock, both
  with `flock` and on the `fcntl`-less fallback path.
- **Process control** — a generation that exceeds `--timeout` is killed as a
  process group; a grandchild spawned by the fake engine is confirmed gone
  afterwards. Already-dead processes and unkillable stubs are handled without raising.
- **Degraded filesystems** — directory `fsync` unavailable, `os.replace` failing
  mid-write (no temp file is left behind), an unremovable lock marker.
- **Verification** — multiple commands, empty command, shell mode with pipes and
  `&&`, and failure handoffs built from either command output or the raised error.
- **CLI** — full lifecycle, dirty-repo refusal and override, refusal to overwrite
  existing state, resume across processes, mutated-task refusal, non-repository
  paths, missing state, exit codes, `--version`, interrupt handling.
- **Packaging** — `python3 -m strata`, the console-script wrapper, and an
  `install.sh` → run → `uninstall.sh` round trip into a temporary prefix.

## 4. Defects found and fixed during this review

The prototype this skill grew out of was reviewed against a live Claude Code
installation. Seven defects were found; all are fixed in 1.0.0.

**A. Handoff compaction could exceed its own hard budget.**
A schema-maximal handoff is ~24,600 bytes after the old final cap, against a
16,000-byte budget — the runner would raise `Handoff exceeds hard budget` and lose
the generation. Compaction is now tiered and shrinks until it fits; the last tier
keeps a minimal navigable core. Verified on the worst case and 500 random handoffs.

**B. The default permission mode made headless runs useless.**
With `--permission-mode auto`, Claude Code denied all four write attempts in live
run 2 (`permission_denials` in the JSON envelope) and the generation ended
`blocked` having changed nothing. The default is now `acceptEdits`.

**C. Hitting the turn limit was reported as a generic engine failure.**
Claude Code exits 1 with `subtype: error_max_turns` and no `structured_output`.
That consumed one of three engine-failure strikes and produced no useful guidance.
Turn limits are now classified separately, get their own strike counter
(`--turn-limit-strikes`), and hand the next generation an explicit "you were cut
off, work in smaller steps" recovery note.

**D. Budget exhaustion was retried.** A budget stop is not transient; retrying it
burns two more generations against the same wall. It now ends the run with
`phase=budget_exhausted`.

**E. State from another build crashed the runner.** `RuntimeState(**obj)` raised a
raw `TypeError` on unknown keys. Loading now checks the schema version explicitly
and ignores unknown keys.

**F. Every outcome returned exit code 0.** Blocked, stalled and ceiling-reached
runs were indistinguishable from success in CI. They now return 3.

**G. `--verify` could not express real check pipelines.** Commands are split with
`shlex`, so `a && b` silently became nonsense arguments. `--verify-shell` now opts
into shell semantics; the default stays non-shell.

## 5. Known limits

- Only Linux was exercised. The Windows branches (`proc.terminate()`,
  `CREATE_NEW_PROCESS_GROUP`) are written but untested, and are the lines excluded
  from the coverage figure.
- Live validation used the `haiku` model and short tasks. Multi-hour runs against a
  large repository are not part of this report.
- Claude Code's `--max-turns` flag is not listed in `--help` on 2.1.231. It works
  today; a future release could remove it, in which case the turn-limit path
  simply stops triggering.
- `history.jsonl` grows without bound. It is diagnostic only and is never sent to
  the model, but it is not rotated.
