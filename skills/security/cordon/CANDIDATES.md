# Second SkillQuarry skill — candidates and selection

Research date: 2026-08-14. Source basis: `RESEARCH.md`.

## Candidate 1 — Cordon: deterministic change envelope

**Problem.** Coding agents can claim success or modify more of a repository than the task intended. Claude Code provides permissions and hooks, but its public issue tracker contains concrete regression/bypass reports; those controls should not be treated as independent proof of the final repository state.

**Target users.** Developers running Claude Code or another coding agent in an existing Git repository, especially unattended/headless work where review needs a deterministic first gate.

**Why existing solutions are insufficient for this job.** The inspected marketplaces and skill collections concentrate on discovery, packaging and development workflows; guardrail projects mainly operate before/during tool calls. None of the inspected projects is used here as a generic post-run Git-visible path/size budget plus independent-verifier acceptance layer.

**Effort.** Medium-high: robust NUL-safe Git parsing, state integrity, atomic writes, process limits, installer and adversarial tests.

**Risk.** Git ignore semantics can hide files; path globs are easy to get subtly wrong; a tool with filesystem access can tamper with audit state. These are explicitly bounded/documented rather than hidden.

**Objectively finished when.** Path allow/deny, commit movement, file/line/byte/binary budgets, verifier veto, crash/resume, process limits, corrupt state and pathological file names all have deterministic tests; core coverage is 100%; install/uninstall is symmetric.

## Candidate 2 — Witness: reproducible agent evidence bundle

**Problem.** Agent-run review often lacks a compact machine-readable record of environment, commands, hashes and verifier output.

**Target users.** Maintainers reviewing agent-generated patches or CI artifacts.

**Why existing solutions are insufficient for this job.** Agent runtimes expose transcripts/output but not a provider-neutral, minimal evidence bundle tied to the resulting files. Marketplace projects validate packages rather than one target-repository run.

**Effort.** Medium.

**Risk.** Captured logs can leak secrets; cryptographic signing without an external key/signing tool would overstate trust. A stdlib-only v1 could hash evidence but not establish signer identity.

**Objectively finished when.** Identical inputs produce a canonical manifest, file hashes replay correctly, secret-prone outputs are opt-in, and tampering is detected by replay tests.

## Candidate 3 — Cartograph: token-bounded repository context map

**Problem.** Large coding repositories make agents waste tokens rediscovering structure and relevant files.

**Target users.** Developers using coding agents on monorepos or unfamiliar codebases.

**Why existing solutions are insufficient for this job.** Skills/subagents improve context organization, but deterministic high-quality relevance ranking across programming languages generally benefits from parsers/indexers that conflict with the no-third-party-package constraint.

**Effort.** High.

**Risk.** A stdlib-only lexical/dependency mapper could look precise while silently missing dynamic imports, generated code or language-specific semantics.

**Objectively finished when.** It obeys a hard byte/token proxy budget and beats a documented baseline on a fixed multilingual retrieval benchmark without hiding missed dependencies.

## Selection

**Cordon is selected.** It complements Strata instead of duplicating it: Strata makes long work survive fresh contexts and crashes, while Cordon independently limits and verifies the resulting Git-visible blast radius. Its core claims are directly measurable with Git and process exit codes, and the complete v1 can be implemented and adversarially tested using only Python's standard library.
