# Cordon research record

Research date: **2026-08-14**. This file records the sources consulted before implementation. Blogs, tutorials and secondary summaries were not used as authority.

## 1. Primary-source findings

### Claude Code CLI and runtime

| Source | Version / ref | What was taken from it |
|---|---|---|
| https://code.claude.com/docs/en/cli-reference | live docs, fetched 2026-08-14 | `-p`/`--print`, `--output-format json`, `--no-session-persistence`, `--max-turns`, `--max-budget-usd`, `--model`, `--effort`, and `--permission-mode`; the page explicitly says `claude --help` does not list every flag. The current `--effort` values documented there are `low`, `medium`, `high`, `xhigh`, `max`, and `ultracode`; Cordon validates exactly this fetched set. |
| https://code.claude.com/docs/en/permission-modes | live docs, fetched 2026-08-14 | semantics of `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, and `plan`; `acceptEdits` auto-accepts file edits/common filesystem operations in the working directory. |
| https://code.claude.com/docs/en/skills | live docs, fetched 2026-08-14 | Claude Code skill discovery/invocation and permission interaction. |
| https://code.claude.com/docs/en/hooks | live docs, fetched 2026-08-14 | hook lifecycle, command/prompt/agent/MCP hook types, and blocking/decision integration. |
| https://code.claude.com/docs/en/sub-agents | live docs, fetched 2026-08-14 | subagents use separate contexts; permissionMode, skills, MCP servers, hooks and worktree isolation fields. |
| https://code.claude.com/docs/en/mcp | live docs, fetched 2026-08-14 | MCP connects external servers/tools; tool access is permission-governed. |
| https://code.claude.com/docs/en/tools-reference | live docs, fetched 2026-08-14 | built-in tool names and the role of MCP for custom tools. |
| https://github.com/anthropics/claude-code/issues/16963 | public issue, fetched 2026-08-14 | historical concrete report that `--max-turns` worked while absent from `claude --help`. This agrees with the current official CLI page's warning that help is not exhaustive. |
| https://github.com/anthropics/claude-code/issues/22055 | public issue, fetched 2026-08-14 | report of an Edit/Write permission regression. Treated as a failure report, not a claim about every current version. |
| https://github.com/anthropics/claude-code/issues/27040 | public issue, fetched 2026-08-14 | report that a deny rule was not honored in a particular setup/version. Treated as a failure report only. |
| https://github.com/anthropics/claude-code/issues/41259 | public issue, fetched 2026-08-14 | report involving permission-setting caching and Edit/Write behavior. |
| https://github.com/anthropics/claude-code/issues/61953 | public issue, fetched 2026-08-14 | report of a workflow in which an agent removed flag files used by a safety hook. This is evidence that model-visible hook state is not a hostile security boundary. |
| `skills/autonomous/strata/TEST_REPORT.md` in this repository | Strata 1.0.0 reference supplied by project owner | local empirical Finding B: headless `--permission-mode auto` denied writes in that measured environment while `acceptEdits` allowed them. Cordon therefore uses `acceptEdits` by design. |

### Public `claude --help` evidence and unresolved drift

The current official CLI reference explicitly states that **`claude --help` does not list every flag**. Public issue #16963 captured a real case where `--max-turns` worked but was absent from help. Strata's supplied test report independently records the same kind of discrepancy on Claude Code 2.1.231.

There is no authenticated `claude` executable in this build sandbox, so this build does **not** claim a local current Claude Code version or local live-agent result. The reviewing machine must run:

```bash
claude --version
claude --help
claude -p "Reply only with OK" --output-format json --no-session-persistence --max-turns 1 --permission-mode acceptEdits
```

The last command is a compatibility probe, not a write test. A separate temporary-repository smoke test is requested in `REVIEW.md`.

### Agent Skills format

| Source | Version / ref | Finding |
|---|---|---|
| https://agentskills.io/specification | live specification, fetched 2026-08-14 | a skill directory requires `SKILL.md`; YAML frontmatter requires `name` and `description`; names are lowercase letters/digits/hyphens and must match the directory; progressive disclosure is recommended. |
| https://github.com/agentskills/agentskills | commit `69ef37e9424c0a7ea9dd2293b559e43ec8176379`, fetched 2026-08-14 | primary repository for the Agent Skills specification/reference tooling. |

Cordon's `SKILL.md` follows the portable mandatory frontmatter subset and keeps runtime details in adjacent documentation.

### Git behavior used by Cordon

| Source | Version / ref | Finding |
|---|---|---|
| https://git-scm.com/docs/git-diff | documentation currently displays Git 2.55.0, fetched 2026-08-14 | `git diff <commit>` compares the working tree against a commit; Cordon uses the armed commit as baseline. |
| https://git-scm.com/docs/diff-format | live docs, fetched 2026-08-14 | `--numstat` is intended for machine consumption; `-z` uses NUL termination. Cordon additionally passes `--no-renames` so each record has one path. |
| https://git-scm.com/docs/git-ls-files | documentation currently displays Git 2.55.0, fetched 2026-08-14 | `--others` selects untracked files; `--exclude-standard` applies standard ignore rules; `-z` NUL-terminates paths. |
| https://git-scm.com/docs/git-rev-parse | live docs, fetched 2026-08-14 | `--verify HEAD` resolves the current baseline commit. |
| https://git-scm.com/docs/gitignore | live docs, fetched 2026-08-14 | `$GIT_DIR/info/exclude` / repository info-exclude is appropriate for repository-local patterns that should not be shared. Cordon records `/.cordon/` there and never edits `.gitignore`. |

The build machine has Git **2.47.3**. The target matrix is Linux/macOS; the reviewer is asked to run the suite against the target machine's Git version.

### Python standard-library behavior used by Cordon

| Source | Version | Finding |
|---|---|---|
| https://docs.python.org/3.10/library/os.html | Python 3.10.20 docs, fetched 2026-08-14 | `os.replace` provides replacement semantics and is required to be atomic on POSIX when successful; `os.fsync` forces written data; `os.lstat` does not follow symlinks. |
| https://docs.python.org/3.10/library/subprocess.html | Python 3.10.20 docs, fetched 2026-08-14 | `subprocess.Popen(..., start_new_session=True)` creates a new session on POSIX, allowing process-group termination without `preexec_fn`. |
| https://docs.python.org/3.10/library/trace.html | Python 3.10.20 docs, fetched 2026-08-14 | stdlib `trace` supplies execution-count data used by the coverage harness. |
| https://docs.python.org/3.10/library/fcntl.html | Python 3.10.20 docs, fetched 2026-08-14 | `fcntl.flock` applies advisory lock operations to an open file descriptor and raises `OSError` on failure; used by the POSIX repository lock. |
| https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/flock.2.html | Apple macOS/BSD `flock(2)` manual page, fetched 2026-08-14 | primary macOS description of advisory `flock`, including non-blocking `LOCK_NB`; supports the macOS target design, while actual execution remains a reviewer/CI requirement. |

No third-party Python package is required at runtime or test time.

### CI actions used by this repository

| Source | Version/ref | Finding |
|---|---|---|
| https://github.com/actions/checkout | README fetched 2026-08-14, current README labels Checkout v7 | official GitHub checkout action; workflow uses `actions/checkout@v7`. |
| https://github.com/actions/setup-python | README fetched 2026-08-14, current README labels setup-python v7 | official GitHub Python setup action; its own basic example uses checkout@v7 and setup-python@v7; workflow uses `actions/setup-python@v7`. |

## 2. Market scan — repositories inspected directly through GitHub/API

Repository metadata below was fetched from `https://api.github.com/repos/<owner>/<repo>`, the repository contents endpoint, and `commits?per_page=1` on **2026-08-14**. Star counts are snapshots, not permanent properties.

| Repository | Stars at fetch | Commit/ref inspected | Structure / strength | Gap relative to Cordon |
|---|---:|---|---|---|
| https://github.com/anthropics/skills | 169,013 | `f6656c1256d5a8adfa37db9110046ef20bac644c` | official skill collection; strong examples and distribution conventions | not a post-run Git change-envelope/verifier |
| https://github.com/anthropics/claude-code | 141,365 | `1f6015b5d578adf79c8527443328a216d6b6a3f1` | official runtime, plugins, examples, changelog and issues | permissions/hooks are runtime controls, not an independent after-the-fact Git budget audit |
| https://github.com/agentskills/agentskills | 24,241 | `69ef37e9424c0a7ea9dd2293b559e43ec8176379` | specification, docs and reference tooling | defines skill packaging, not repository outcome enforcement |
| https://github.com/vercel-labs/skills | 28,830 | `c6f69c631292444cc541ac6d91e2226b0ff247da` from commits endpoint | installer/discovery tooling plus skills/tests | focuses on skill installation/discovery rather than bounded Git outcomes |
| https://github.com/obra/superpowers | 271,742 | `b36e0829c6d0140e93cfef2ca599b1b07d4a7797` | cross-agent workflow skills and plugin manifests with tests | strong development method, but not a deterministic post-run diff budget |
| https://github.com/wshobson/agents | 38,778 | `c4b82b0ad771190355eb8e204b1329732a18449a` from commits endpoint | agent/skill/plugin layouts for several agent ecosystems | broad specialization/catalog, not independent Git result acceptance |
| https://github.com/daymade/claude-code-skills | 1,333 | `af064841b5b2ca524d1fb55c7c64a44e24e0c067` | production-minded marketplace with changelog, tests, gitleaks/pre-commit support | quality around the skill repository; no generic change-envelope around arbitrary target repos |
| https://github.com/laurigates/claude-plugins | 51 | `442d0a4e7cffe6b677a6d3872d15c9cb70de4308` | large plugin collection, tests, MCP/version checks, security tooling | plugin workflows rather than provider-neutral post-run Git acceptance |
| https://github.com/hyperskill/claude-code-marketplace | 3 | `556437f6f0ed6afc9e6764f1c6cac017c34c38f7` | small curated plugin marketplace | distribution/catalog role; no Git blast-radius auditor |
| https://github.com/netresearch/claude-code-marketplace | 51 | `e01c46020b722bf12dcbf09d4e4429625c94b93c` | portable agent-skill catalog, validation scripts and website | strong catalog validation, not target-repository outcome enforcement |
| https://github.com/dwarvesf/claude-guardrails | 31 | `4396c03a89837da3b026ebd73d4416b9589f4c5f` | permission deny rules, shell hooks, prompt-injection patterns, tests | primarily pre-tool/runtime guardrails; Cordon intentionally checks the resulting Git-visible state afterwards |

### GitHub metadata discrepancy noted, not hidden

For at least `vercel-labs/skills` and `wshobson/agents`, the repository metadata `pushed_at` observed during research was newer than the commit returned by the default-branch `commits?per_page=1` request captured in this session. Cordon does not depend on those timestamps. The table therefore records the exact commit returned by the commits endpoint and does not infer an unobserved SHA.

## 3. Market gap

The inspected ecosystem is strong in four areas: skill packaging, skill discovery/installers, agent workflow methodology, and pre-tool permission/hook guardrails. The failure reports in Claude Code's own issue tracker also show why those controls should not be described as an infallible hostile boundary.

The gap selected for SkillQuarry is a small, dependency-free component that asks a different question **after work has happened**:

> Does the Git-visible result stay inside an explicitly armed path and size budget, and do independent commands agree that the result is acceptable?

Cordon therefore does not replace Claude Code permissions, hooks, worktree isolation or code review. It adds deterministic after-the-fact evidence based on Git plus independent verifier exit codes.

## 4. Open uncertainties for the real target machine

1. **Live Claude Code compatibility.** No `claude` binary/authentication exists in this sandbox. Verify exact installed version and the seven Cordon flags using `REVIEW.md`.
2. **Python 3.10 execution.** The code is written to Python >=3.10 syntax/stdlib, but the sandbox only has Python 3.13.5. CI is provided with a 3.10–3.13 matrix; the reviewer should execute at least 3.10 locally/CI.
3. **macOS process-group behavior.** POSIX branches are exercised on Linux, including TERM→KILL escalation. macOS is a target but was not available in this sandbox; the supplied workflow includes macOS.
4. **Ignored files.** Cordon v1 intentionally audits Git-visible tracked changes and non-ignored untracked files. Files hidden by Git ignore rules are outside its evidence model. Do not use Cordon as a hostile sandbox for secrets/build caches/ignored state.
5. **Filesystem adversary.** State hashes detect accidental/inconsistent edits, not a malicious process that can rewrite both state and hashes. Cordon is an audit/acceptance layer, not a tamper-proof security boundary.
6. **Git implementation/version.** Tests passed on Git 2.47.3; the docs fetched displayed newer Git documentation. The used command forms are covered by the target-machine suite, which is the final compatibility proof.
