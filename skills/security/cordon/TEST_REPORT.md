# Cordon 1.0.0 — Test Report

Recorded: **2026-08-14**

This report separates what was actually executed in the build sandbox from what remains for the reviewing machine. No authenticated Claude Code binary was present here, so no live Claude result is claimed.

## Environment actually used

| Component | Observed value |
|---|---|
| OS | Linux 6.18.35 x86_64, glibc 2.41 |
| Python | CPython 3.13.5 |
| Git | 2.47.3 |
| `/bin/sh` | `/usr/bin/dash` |
| Claude Code | **not installed / not available in PATH** |
| Third-party Python packages | none required or imported |
| Coverage engine | Python stdlib `trace` through `tests/run_tests.py` |

Python 3.10 is a declared target but was not installed in this sandbox. The supplied CI workflow covers 3.10–3.13 and Linux/macOS; those jobs must be executed by GitHub/target infrastructure before claiming those environments passed.

## Exact reproduction command

From `skills/security/cordon/`:

```bash
python3 tests/run_tests.py --min 100
```

Recorded terminal tail after the final fix:

```text
Ran 57 tests in 21.543s

OK

coverage: core.py 100.0%  (962/962 executable lines)
```

The test runner discovers the complete `tests/` suite, runs it under `trace.Trace(count=True, trace=False)`, derives executable lines from Python code objects, excludes only lines explicitly marked `# pragma: no cover`, and exits non-zero below `--min`.

### Coverage exclusions

The only intended source exclusions in `core.py` are Windows-only process branches, because Windows is not a target for this release. The package `__main__` guard is outside `core.py` and therefore outside the measured core target. No Linux/macOS core branch was excluded to reach 100%.

## Five required user scenarios

### 1. Beginner — simplest intended flow: PASS

Test: `test_scenarios.BeginnerScenario.test_manual_arm_edit_check`

Evidence: creates a real temporary Git repository, arms a manual envelope, changes an allowed file, runs a real Cordon check, and receives acceptance.

Reproduce:

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_scenarios -k manual_arm_edit_check
```

Expected: one test, `OK`.

### 2. Everyday developer — multi-step Claude-shaped use: PASS

Test: `test_scenarios.EverydayScenario.test_claude_multi_step_with_verifier`

Evidence: real Git/filesystem; fake Claude binary receives the exact Cordon-used CLI contract, changes multiple allowed files, and an independent verifier must pass. The test asserts `--permission-mode acceptEdits` appears in the invocation.

Reproduce:

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_scenarios -k claude_multi_step_with_verifier
```

Expected: one test, `OK`.

### 3. Advanced — crash/failure and resume: PASS

Test: `test_scenarios.AdvancedScenario.test_crash_then_resume_from_partial_change`

Evidence: first fake-Claude process changes a file then exits non-zero. Cordon persists engine failure; `resume` starts a fresh second process, includes recovery context, completes the repair, and passes the audit.

Reproduce:

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_scenarios -k crash_then_resume_from_partial_change
```

Expected: one test, `OK`.

### 4. Expert — agent claims success, independent proof rejects it: PASS

Test: `test_scenarios.ExpertScenario.test_agent_claims_success_verifier_vetoes_then_resume_repairs`

Evidence: fake Claude prints a success claim while leaving the repository in a state that fails the configured verifier. Cordon records `rejected`; a later fresh resume fixes the failure and only then reaches `accepted`.

Reproduce:

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_scenarios -k agent_claims_success_verifier_vetoes_then_resume_repairs
```

Expected: one test, `OK`.

### 5. Adversarial — corrupt state, loop ceiling, scope break, pathological filename: PASS

Test: `test_scenarios.AdversarialScenario.test_corrupt_state_scope_break_attempt_ceiling_and_pathological_name`

Evidence includes a legal Git filename containing newline/tab characters, policy rejection outside scope, corrupted state rejection, and attempt-ceiling enforcement.

Reproduce:

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_scenarios -k corrupt_state_scope_break_attempt_ceiling_and_pathological_name
```

Expected: one test, `OK`.

## Deterministic worst-case checks

Random fuzzing is not used as the only argument for a hard bound.

### Change budgets

`test_budget_worst_cases_exact_boundary_and_one_over` constructs an exact accepted boundary and then exceeds it. The implementation compares integer counts with strict `>` so equality is accepted and `limit + 1` is rejected.

### Untracked scan resource bound

Cordon first sums `lstat` sizes for Git-visible untracked entries. The hard scan ceiling is **64 MiB = 67,108,864 bytes**. The dedicated boundary test patches that constant to 64 bytes, proves exactly 64 does not trigger the preflight cap, then proves 65 emits the exact `65 > 64` violation. A separate growth-after-preflight test gives the reader a 64-byte budget but a deterministic 65-byte stream; the reader consumes only budget + one detection byte and rejects the scan. This is arithmetic boundary testing, not a probability claim.

### Captured subprocess output

Each stdout and stderr buffer has a configured byte cap (default 4 MiB each). `_reader_thread` retains no more than `cap` bytes even though it may read one additional chunk to detect overflow; the process is then terminated. A deterministic immediate-thread unit test covers the output-limit termination branch without relying on scheduler timing.

### Attempts

`max_attempts` is persisted as a positive integer. `resume` refuses when current attempts are already at the ceiling; it cannot create an unbounded retry loop through the Cordon API.

### Verifier fan-out and retained evidence

At most 8 verifier commands are accepted, each at most 4,096 characters. Each verifier process is still subject to the configured stdout/stderr process cap; persistent evidence retains only the first 16,384 bytes per stream plus a fixed truncation marker. The maximum retained raw excerpt payload is therefore 262,144 bytes across all verifier stdout/stderr streams before JSON escaping and metadata.

### Pattern count and length

At most 256 combined allow/deny patterns are accepted; each is at most 512 characters. This bounds regex construction work from the policy itself.

## Additional hardening exercised

The 56-test suite also covers:

- atomic-write temp cleanup after a forced `os.replace` failure;
- directory `fsync` supported/unsupported error handling;
- state/config schema and hash inconsistencies;
- concurrent repository lock refusal, including a second Cordon operation while a fake agent process is still alive;
- NUL-safe Git numstat parsing and malformed records;
- tracked binary accounting;
- untracked symlink, directory/special path, disappearing-file and read-error paths;
- changed-path `lstat` race and unsupported file types;
- commit movement blocked by default and allowed only when explicitly configured;
- verifier parse failure, timeout and output overflow;
- policy rejection short-circuiting verifier execution;
- subprocess missing-binary, timeout, TERM→KILL escalation and stuck-reader errors;
- interrupted and failed Claude attempts persisted distinctly;
- resume rejection for out-of-policy partial changes;
- CLI exit code 3 on audit rejection;
- install, identical reinstall and uninstall symmetry;
- uninstall leaving repository `.cordon` state untouched.

## Defects found during this build and fixed

### C1 — `**` failed on a legal newline in a Git filename

**Found by:** adversarial scenario.

**Cause:** the first glob compiler used regex `.` semantics for `**`; Python `.` does not match a newline unless DOTALL is enabled. Git permits newline bytes in Unix filenames.

**Fix:** compile Cordon glob regexes with `re.DOTALL`; the adversarial scenario now uses a newline/tab filename and passes through `src/**` correctly.

**Regression command:**

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_scenarios -k pathological_name
```

### C2 — untracked text measurement had no global scan ceiling

**Found by:** manual worst-case analysis before random testing.

**Cause:** each untracked regular file was individually streamed, but total visible untracked content could be arbitrarily large, making one audit consume unbounded I/O time.

**Fix:** metadata preflight sums Git-visible untracked byte sizes. Above 64 MiB Cordon rejects without content-scanning those files. Exact-boundary 64/65-byte tests validate the inequality.

**Regression command:**

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k scan_cap_is_mathematical_not_random
```

### C3 — installer smoke test was falsely green when inherited `PYTHONPATH` exposed source tree

**Found by:** rerunning the documented command from the skill directory rather than the repository-root harness invocation.

**Cause:** installer initially wrote package files directly into the release directory, while the launcher expected that directory to contain a `cordon/` package. An inherited development `PYTHONPATH` let `python3 -m cordon` find the source tree, hiding the install-layout bug.

**Fix:** releases now contain `release/cordon/*.py`, and installer tests explicitly remove inherited `PYTHONPATH` before executing the installed launcher.

**Regression command:**

```bash
python3 -m unittest -v tests/test_install_cli.py -k install_reinstall_and_uninstall_are_symmetric
```

### C4 — shell-quoted install prefix could break on an apostrophe

**Found by:** installation portability review after C3.

**Cause:** the first fixed installer launcher embedded the release path inside single-quoted shell text. A valid installation prefix containing an apostrophe could make that launcher syntactically invalid.

**Fix:** the installed launcher is now a Python entry script whose release path is emitted with Python `repr`; the installer regression test deliberately uses a prefix containing both spaces and an apostrophe.

**Regression command:**

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_install_cli -k install_reinstall_and_uninstall_are_symmetric
```

### C5 — non-UTF-8 POSIX filename could break JSON serialization

**Found by:** adversarial filename review after the newline/tab test.

**Cause:** Git paths are byte strings on POSIX. `os.fsdecode` can represent undecodable bytes with surrogate code points, while JSON encoded with `ensure_ascii=False` can fail when those surrogates are encoded to UTF-8.

**Fix:** canonical persisted JSON and CLI JSON use ASCII JSON escapes. A real temporary Git repository test creates a filename containing byte `0xFF`, audits it successfully, and proves the serialized payload contains a `\udc..` escape instead of failing.

**Regression command:**

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_scenarios -k non_utf8_git_filename_survives_audit_and_json
```

### C6 — run arm/setup could race before the repository lock

**Found by:** final concurrency review after the functional suite was already green.

**Cause:** the first implementation stored its lock inside `.cordon/` and `run` armed the envelope before acquiring the lock used by the agent attempt. Two Cordon processes therefore had a narrow interval in which both could enter setup against the same repository.

**Fix:** the synchronization inode now lives in Git metadata as `.git/cordon.lock` (resolved with `git rev-parse --git-path`), outside semantic `.cordon/` state. `run` holds one OS advisory lock continuously across arm/setup and the complete agent attempt. A real concurrency regression starts a sleeping fake-agent subprocess and proves a simultaneous `check` is rejected with `LockError` until the first operation exits.

The zero-length lock inode is intentionally stable and contains no semantic data; replacing a held lock inode would defeat `flock` mutual exclusion. All semantic state/content writes continue to use temp-file + `fsync` + `os.replace`.

**Regression command:**

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k run_holds_repository_lock_for_entire_agent_attempt
```

### C7 — a growing untracked file could outrun the preflight scan budget

**Found by:** manual resource-bound audit after C6, before release packaging.

**Cause:** the first 64 MiB scan guard summed `lstat` sizes before reading. If an untracked regular file grew after that preflight, the content reader could continue past the advertised hard I/O ceiling; a moderate growth race could also undercount the observed working-byte budget.

**Fix:** the reader now receives the exact remaining global scan budget and reads at most that budget plus one detection byte. It returns an explicit violation when the extra byte exists, tracks actual scanned bytes cumulatively across files, and uses the measured size when scanning succeeds. The regression uses a one-byte on-disk file with a deterministic 65-byte read stream under a 64-byte budget, proving the post-preflight growth path is rejected.

**Regression command:**

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k streaming_scan_cap_handles_growth_after_preflight
```

### C8 — non-finite numeric limits could bypass timeout validation

**Found by:** manual pathological-input review after the scan-cap fix.

**Cause:** Python accepts `float("nan")` and `float("inf")` from numeric input. A simple `timeout <= 0` check does not reject NaN, and a NaN deadline makes normal deadline comparisons false.

**Fix:** process timeouts, Claude timeouts and optional dollar budgets must now be finite positive numbers via `math.isfinite`; output caps must be positive non-boolean integers. Tests cover zero, negative, boolean, NaN and infinity.

**Regression command:**

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k process_invalid_cap_and_missing_binary
PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k invalid_claude_configs
```

### C9 — verifier evidence could accumulate too much persistent output

**Found by:** cumulative-memory calculation during resource review.

**Cause:** per-process stream caps bounded one verifier, but an unbounded verifier list could still retain many bounded outputs and inflate `audit.json` / `state.json`.

**Fix:** Cordon accepts at most **8** verifier commands, each at most **4,096 characters**. Process overflow still rejects normally, while successful verifier evidence stores at most the first **16,384 bytes** of each stdout/stderr stream plus a truncation marker. With 8 verifiers that bounds retained raw excerpts to 8 × 2 × 16,384 = **262,144 bytes** before JSON escaping/metadata.

**Regression command:**

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k verifier_parse_errors
PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k verifier_timeout_output_limit_and_policy_short_circuit
```

### C10 — Claude prompt contradicted `--allow-commits` and omitted numeric budgets

**Found by:** final wrapper-contract review.

**Cause:** the independent auditor correctly supported `allow_commits`, but the first wrapped-agent prompt always said `Do not commit` and did not tell Claude the numeric envelope limits.

**Fix:** the prompt now mirrors the armed commit rule and includes exact file, added-line, deleted-line, working-byte and binary-file ceilings. Independent Git enforcement remains authoritative.

**Regression command:**

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k prompt_matches_budgets_and_commit_policy
```

### C11 — index flags could hide a tracked change from the audit

**Found by:** independent review on the target machine (Claude Code 2.1.231, Linux).

**Cause:** `git update-index --assume-unchanged <path>` and `--skip-worktree <path>` remove a
tracked file from `git diff` output. Cordon audited that diff, so an out-of-policy modification
to such a file was reported as `"passed": true` with an empty `changed_files` list while the
modified content sat on disk. The documented ignored-file caveat did not cover this: the files
are tracked, not ignored.

**Fix:** `index_hidden_paths()` reads `git ls-files -v -z` and treats a lowercase status letter
(assume-unchanged) or `S` (skip-worktree) as a hidden path. `arm` refuses to start while such a
flag exists and names the remediation command; `audit_policy` reports any flag appearing later as
a violation, so a blind spot can never be reported as a clean result. The report of hidden paths
is bounded by `MAX_HIDDEN_PATHS_REPORTED`.

**Regression command:**

```bash
PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k IndexFlagTests
```

## Known limits — no claims beyond these

1. ~~**No live Claude Code execution in this sandbox.**~~ **Closed by review:** the smoke test from `REVIEW.md` ran against Claude Code 2.1.231 on Linux — exit `0`, `"passed": true`, only the requested one-line diff, no `.cordon` path in `git status`. Every flag Cordon emits exists in that release.
2. ~~**No Python 3.10 runtime yet.**~~ **Closed by CI:** the suite is green on CPython 3.10, 3.11, 3.12 and 3.13 (Linux) and 3.11–3.13 (macOS).
3. **macOS is covered by CI, with one filesystem difference.** The macOS jobs exposed that APFS rejects non-UTF-8 filenames outright (`OSError: [Errno 92] Illegal byte sequence`), which ext4 accepts. The two byte-path tests now detect that at runtime: where such a name cannot exist, they assert the decoding/reporting logic directly and skip the Git part instead of failing. Cordon itself is unchanged; the difference belongs to the filesystem.
4. **Ignored files are not audited in v1.** `git ls-files --others --exclude-standard` intentionally excludes ignored untracked files. Changes to ignored files can be invisible to Cordon.
5. **External symlink targets are outside the Git evidence model.** Cordon can account for the symlink object, but a write performed through a repository symlink to a target outside the repository is not a Git-visible target-repository change.
6. **Not tamper-proof against a hostile local process.** Hashes catch inconsistent/accidental state changes, not an attacker that rewrites config/state plus hashes.
7. **Verifier correctness is external.** Cordon proves process exit status/output bounds, not the logical adequacy of a user's verifier.
8. **No shell interpretation for verifier strings.** This is intentional. Complex shell logic must live in a reviewed executable script.
9. **Windows is not a release target.** Windows process branches are marked `# pragma: no cover` and untested.
10. **Race window is finite, not eliminated.** Like any worktree audit without filesystem freezing, files can change between individual Git/stat/read operations. Cordon names observed races when possible; hostile concurrent mutation requires stronger isolation.

## Target-machine checks still required

See `REVIEW.md` for compact commands. The three highest-value checks are live Claude Code invocation/write behavior, Python 3.10 execution, and macOS process termination/installer behavior.
