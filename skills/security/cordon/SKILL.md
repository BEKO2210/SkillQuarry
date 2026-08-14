---
name: cordon
description: Use when a coding agent must be constrained to a measurable Git-visible change envelope and its result must be independently verified before acceptance. Arms allowed and denied repository paths plus file, line, byte, binary and commit budgets; can wrap Claude Code or audit any agent run manually; verifier exit codes overrule the model's success claim. Trigger phrases include "only change these files", "limit blast radius", "verify agent changes", "guard this refactor", "agent changed too much", "audit the diff", "run Claude inside a change budget".
license: Apache-2.0
compatibility: Requires Python 3.10+ and Git. Claude Code is required only for cordon run/resume. Linux and macOS are targets; Windows is not tested.
metadata:
  author: SkillQuarry
  version: "1.0.0"
---

# Cordon — deterministic change envelopes

Cordon is a post-run acceptance layer for coding-agent changes. It snapshots the
current Git `HEAD`, records an explicit repository-relative path and size policy,
then accepts the result only when the Git-visible changes stay inside that policy
and every independent verifier exits zero.

Use Cordon when “the agent should only touch X” must be checked by code rather
than remembered by the agent. Do not call Cordon a sandbox: ignored files are
outside its v1 evidence model, and a process with unrestricted filesystem access
can tamper with Cordon's own state.

## Choose a mode

### Vendor-neutral: arm, run any agent, check

```bash
cordon arm "update parser only" \
  --allow "src/parser/**" \
  --allow "tests/parser/**" \
  --deny "src/parser/generated/**" \
  --max-files 8 \
  --max-added-lines 400 \
  --max-deleted-lines 200 \
  --verify "python3 -m unittest discover -s tests"

# Run the coding agent yourself.
cordon check
```

This mode never invokes an AI service.

### Claude Code wrapper

```bash
cordon run "Fix the parser regression without changing generated files." \
  --allow "src/parser/**" \
  --allow "tests/parser/**" \
  --deny "src/parser/generated/**" \
  --verify "python3 -m unittest discover -s tests" \
  --max-files 8 \
  --max-added-lines 400 \
  --max-deleted-lines 200 \
  --max-turns 20 \
  --max-budget-usd 2
```

Cordon launches one fresh `claude -p` process with JSON output, session
persistence disabled and permission mode `acceptEdits`. A failed/interrupted run
can be retried with a fresh process using `cordon resume`, but only while the
partial Git-visible changes still satisfy the armed envelope and the attempt
ceiling has not been reached.

## Read the result

| Exit | Meaning |
|---:|---|
| `0` | audit accepted |
| `2` | Cordon refused the operation or state/policy is invalid |
| `3` | agent/process finished, but the Git policy or a verifier rejected the result |
| `4` | wrapped Claude process failed, timed out, or exceeded captured-output limit |

`cordon status` reports the current phase and last audit. `cordon reset` removes
only `.cordon/`; it does not revert, delete or commit repository files.

## Policy rules

- At least one `--allow` pattern is mandatory.
- `--deny` always wins over `--allow`.
- Patterns are repo-relative Cordon globs: `*` does not cross `/`, `**` does,
  and `?` matches one non-`/` character.
- Cordon rejects absolute-ish patterns (`/x`, `./x`), NUL bytes, and explicit
  `.` / `..` path segments.
- HEAD movement is rejected by default. Use `--allow-commits` only when commits
  are an intentional part of the task.
- Budgets are inclusive: the exact limit is accepted; one over is rejected.
- Verifiers are parsed with `shlex.split` and executed directly, not through a
  shell. Shell operators such as `&&`, pipes and redirects are therefore not
  interpreted.

## State and recovery

Cordon stores state in `.cordon/` and registers `/.cordon/` in
`.git/info/exclude`. It never edits `.gitignore`.

Cordon also refuses to arm while a tracked file carries the `assume-unchanged` or
`skip-worktree` index flag, because such a file cannot be audited. Clear the flag
with `git update-index --no-assume-unchanged <path>` instead of working around it.

Writes to Cordon semantic state are temp-file + `fsync` + `os.replace`. A
zero-length synchronization inode resolved through Git metadata (`cordon.lock`) is
held with an OS advisory lock; it is not part of `.cordon/` state and is never
substituted while locked. The lock prevents two Cordon operations from owning the
same repository state simultaneously, including arm/setup plus a wrapped agent
attempt. A Claude attempt is marked `running` before the child starts; keyboard
interruption is persisted as `interrupted`; engine errors are persisted and may be
resumed.

## What Cordon proves — and what it does not

Cordon can prove, for the armed baseline and Git implementation it runs against,
that the **Git-visible** tracked changes plus non-ignored untracked files observed
at audit time meet its policy and that configured verifier processes exited zero.

It does **not** prove:

- that ignored files were untouched;
- that the repository is safe against a malicious process able to rewrite state;
- that a verifier is logically correct;
- that permission/hooks in an agent runtime cannot be bypassed;
- that code is secure merely because the diff is small.

Review the diff after acceptance. Cordon is a deterministic gate, not a replacement
for code review or OS-level sandboxing.

Full implementation and boundary details: `README.md`. Source evidence:
`RESEARCH.md`. Reproducible tests and known limits: `TEST_REPORT.md`.
