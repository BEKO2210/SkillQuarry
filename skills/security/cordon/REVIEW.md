# Cordon review card

Use this after overlaying the skill onto SkillQuarry. Do not trust this report; run the commands.

| Claim | Evidence in repo | Verification command | Expected output |
|---|---|---|---|
| Core has full measured line coverage | `tests/run_tests.py`, `TEST_REPORT.md` | `cd skills/security/cordon && python3 tests/run_tests.py --min 100` | `Ran 64 tests ... OK` and `coverage: core.py 100.0%  (989/989 executable lines)` |
| No Python package dependency | `pyproject.toml`, imports | `cd skills/security/cordon && python3 -c 'import ast,pathlib; print("stdlib-only source parsed", len(list(pathlib.Path("src/cordon").glob("*.py"))))'` | `stdlib-only source parsed 4` |
| Installer works without source-tree PYTHONPATH | isolated installer test | `cd skills/security/cordon && env -u PYTHONPATH sh -c 'PYTHONPATH=src:tests python3 -m unittest -v test_install_cli -k install_reinstall_and_uninstall_are_symmetric'` | one test, `OK` |
| State is local-excluded, `.gitignore` untouched | `ensure_local_exclude`, scenario tests | run beginner scenario, then inspect its temp-repo logic in `tests/harness.py`; additionally use the manual smoke test below | `.git/info/exclude` contains `/.cordon/`; `.gitignore` unchanged/need not exist |
| Agent success cannot override verifier failure | expert scenario | `cd skills/security/cordon && PYTHONPATH=src:tests python3 -m unittest -v test_scenarios -k agent_claims_success_verifier_vetoes_then_resume_repairs` | one test, `OK` |
| 64 MiB untracked-content hard ceiling is arithmetic | hardening test | `cd skills/security/cordon && PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k scan_cap_is_mathematical_not_random` | one test, `OK` |
| Cordon serializes arm + wrapped attempt | real concurrency test | `cd skills/security/cordon && PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k run_holds_repository_lock_for_entire_agent_attempt` | one test, `OK`; simultaneous `check` is rejected while fake agent is alive |
| Growing untracked files cannot outrun the scan budget | deterministic growth test | `cd skills/security/cordon && PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k streaming_scan_cap_handles_growth_after_preflight` | one test, `OK` |
| Verifier fan-out/evidence are hard-bounded | validation + truncation tests | `cd skills/security/cordon && PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k verifier_parse_errors && PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k verifier_timeout_output_limit_and_policy_short_circuit` | both selected tests report `OK` |
| NaN/infinite timeout/budget inputs are rejected | numeric validation tests | `cd skills/security/cordon && PYTHONPATH=src:tests python3 -m unittest -v test_hardening -k invalid_claude_configs` | one test, `OK` |
| Cordon uses `acceptEdits`, not `auto` | `build_claude_args`, everyday scenario | `grep -n 'permission-mode.*acceptEdits' skills/security/cordon/src/cordon/core.py` | one source line building that exact pair |
| Claude flags are source-recorded | `RESEARCH.md` | compare `build_claude_args()` to https://code.claude.com/docs/en/cli-reference and local `claude --help` | every emitted flag is in official CLI reference; help may be incomplete per that same reference |

## Live Claude Code smoke test — required on the real machine

First record the installed program:

```bash
claude --version
claude --help
```

Then create a disposable Git repository and run Cordon against it:

```bash
tmp=$(mktemp -d)
cd "$tmp"
git init -q
git config user.email reviewer@example.invalid
git config user.name "Cordon Reviewer"
mkdir src
echo 'VALUE = 1' > src/app.py
git add . && git commit -qm baseline

/path/to/SkillQuarry/skills/security/cordon/install.sh

cordon run "Change VALUE from 1 to 2 in src/app.py and do nothing else." \
  --allow "src/**" \
  --max-files 1 \
  --max-added-lines 1 \
  --max-deleted-lines 1 \
  --max-binary-files 0 \
  --verify "git diff --check" \
  --max-turns 5
```

Expected acceptance criteria, not an invented transcript: process exit `0`; audit JSON has `"passed": true`; `git diff -- src/app.py` shows only the requested value change; `git status --short` shows no `.cordon` path.

## Three places I am least certain — please target these

1. ~~**Real Claude Code on the review machine.**~~ **Done:** the smoke test ran against Claude Code 2.1.231 on Linux — exit `0`, `"passed": true`, only the requested diff, no `.cordon` path in `git status`. Every emitted flag exists in that release.
2. **Python 3.10 specifically.** Still open — the review machine had 3.12.3 only; grammar parses against 3.10 and no post-3.10 stdlib API is used. Run the full suite under the oldest supported interpreter: `python3.10 tests/run_tests.py --min 100`.
3. **macOS process groups/filesystem durability.** Linux exercised POSIX TERM→KILL and `fsync` behavior. Run the full suite on macOS and specifically repeat timeout/output-limit tests plus installer/uninstaller tests.
