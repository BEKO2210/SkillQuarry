<div align="center">

# ⛏️ SkillQuarry

### The open marketplace for agent skills

**Discover, build, test, share, and install reusable capabilities for AI coding agents.**

<br>

[![Stars](https://img.shields.io/github/stars/BEKO2210/SkillQuarry?style=for-the-badge&logo=github&label=Stars)](https://github.com/BEKO2210/SkillQuarry/stargazers)
[![Forks](https://img.shields.io/github/forks/BEKO2210/SkillQuarry?style=for-the-badge&logo=github&label=Forks)](https://github.com/BEKO2210/SkillQuarry/network/members)
[![Issues](https://img.shields.io/github/issues/BEKO2210/SkillQuarry?style=for-the-badge&logo=github&label=Issues)](https://github.com/BEKO2210/SkillQuarry/issues)
[![Pull Requests](https://img.shields.io/github/issues-pr/BEKO2210/SkillQuarry?style=for-the-badge&logo=github&label=Pull%20Requests)](https://github.com/BEKO2210/SkillQuarry/pulls)
[![License](https://img.shields.io/github/license/BEKO2210/SkillQuarry?style=for-the-badge)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/BEKO2210/SkillQuarry?style=for-the-badge&logo=git)](https://github.com/BEKO2210/SkillQuarry/commits/main)

<br>

[**Overview**](#overview) ·
[**Marketplace**](#skill-marketplace) ·
[**Skill Standard**](#skill-standard) ·
[**Ralph GH**](#ralph-generational-handoff) ·
[**Security**](#security) ·
[**Roadmap**](#roadmap)

<br>

> **Build capabilities once. Share intelligence everywhere.**

</div>

---

## Overview

**SkillQuarry** is an open-source ecosystem and future marketplace for reusable AI-agent skills.

Modern coding agents are powerful, but many of their best capabilities are still trapped inside:

- giant prompts
- private configuration files
- shell scripts
- hooks
- isolated repositories
- undocumented workflows
- one-off automation systems

SkillQuarry aims to turn those capabilities into reusable building blocks that can be:

**discovered, inspected, tested, versioned, installed, shared, and composed.**

A SkillQuarry skill can teach an agent how to:

- debug software
- review pull requests
- perform security audits
- improve UI and UX
- run and diagnose tests
- manage releases
- optimize context usage
- automate repository workflows
- recover from interrupted work
- generate documentation
- orchestrate autonomous coding loops
- coordinate specialized agents
- perform DevOps workflows
- handle mobile development tasks

The goal is simple:

> **Stop rebuilding useful agent behavior from scratch.**

---

## Why SkillQuarry?

Software has package managers.

Developers have npm, Cargo, PyPI, Maven, Homebrew, and countless other ecosystems for sharing reusable functionality.

AI agents need something similar for **capabilities**.

SkillQuarry is designed around that idea.

Instead of copying a 500-line prompt from one project into another, a reusable capability should eventually be installable like a package.

```bash
skillquarry search security
skillquarry install repository-auditor
skillquarry update
```

These CLI commands represent the planned SkillQuarry experience and are not yet guaranteed to be implemented.

---

## Core Principles

### Open

Skills should be inspectable whenever possible.

### Vendor-neutral

SkillQuarry should not depend on a single AI provider.

### Portable

A capability should be reusable across projects.

### Testable

Agent behavior should be validated instead of trusted blindly.

### Versioned

Changes to skills should be traceable.

### Composable

Small specialized skills should be able to work together.

### Secure

Permissions and executable behavior should be transparent.

### Fail-safe

Autonomous workflows should prefer stopping safely over destructive guessing.

---

## Agent Ecosystem

SkillQuarry is intended to support adapters and skills for multiple agent environments.

<div align="center">

![Claude Code](https://img.shields.io/badge/Claude_Code-Target-191919?style=for-the-badge)
![OpenAI Codex](https://img.shields.io/badge/OpenAI_Codex-Target-191919?style=for-the-badge)
![Gemini](https://img.shields.io/badge/Gemini-Target-191919?style=for-the-badge)
![MCP](https://img.shields.io/badge/MCP-Target-191919?style=for-the-badge)

</div>

Individual skills may support only a subset of these environments.

Compatibility labels describe technical targets only and do not imply affiliation or endorsement.

---

# Skill Marketplace

SkillQuarry is intended to become a searchable marketplace for agent capabilities.

Potential categories include:

| Category | Examples |
|---|---|
| 🧠 Agent Intelligence | Planning, context management, handoffs |
| 💻 Coding | Debugging, refactoring, migrations |
| 🧪 Testing | Unit, integration, E2E, regression |
| 🔐 Security | Auditing, hardening, dependency analysis |
| 🎨 UI / UX | Accessibility, responsive design, design review |
| 📦 DevOps | CI/CD, Docker, deployment, releases |
| 📱 Mobile | Android, iOS, store workflows |
| 🌐 Web | Frontend, backend, APIs, performance |
| 📚 Documentation | README files, architecture, API docs |
| 🤖 Autonomous Agents | Ralph loops, repair agents, orchestration |
| 🔌 Integrations | MCP, hooks, APIs |
| 🛠️ Utilities | Git, repository inspection, automation |

A future marketplace listing could expose information such as:

- name
- description
- version
- author
- license
- supported agents
- operating-system compatibility
- required tools
- permissions
- dependencies
- checksum
- test status
- security status
- source repository
- release history

---

# Skill Standard

A SkillQuarry package should be understandable without requiring users to reverse-engineer it.

A mature skill may eventually look like this:

```text
my-skill/
├── SKILL.md
├── skill.json
├── README.md
├── tests/
├── examples/
├── hooks/
└── scripts/
```

Not every skill needs every file or directory.

The SkillQuarry specification is still being developed.

---

## Example Manifest

A future manifest could look similar to this:

```json
{
  "name": "example-skill",
  "version": "1.0.0",
  "description": "A reusable capability for AI coding agents.",
  "category": "coding",
  "license": "Apache-2.0",
  "compatibility": [
    "claude-code",
    "codex"
  ]
}
```

Additional metadata may eventually describe:

- filesystem access
- network access
- shell access
- external APIs
- required binaries
- supported platforms
- dependency requirements
- permission scopes
- maintainer information
- integrity checks

---

# Featured Concept

## Ralph Generational Handoff

### Fresh context. Persistent progress. Controlled autonomy.

One of the first systems being developed around SkillQuarry is **Ralph Generational Handoff**.

Traditional autonomous agent loops can accumulate increasingly large conversation histories.

Over long-running tasks this may lead to:

- unnecessary context growth
- increased token processing
- stale information
- irrelevant historical context
- repeated mistakes
- difficult crash recovery
- runaway autonomous loops

Ralph Generational Handoff uses a different architecture.

Each generation performs work, verifies its progress, creates a compact handoff, and then terminates.

The next generation receives a fresh context containing only the information required to continue.

```text
Generation 001
      │
      ├── Work
      ├── Test
      ├── Verify
      │
      └── Compact Handoff
               │
               ▼
        Context terminates
               │
               ▼
        Fresh Generation
               │
               ▼
Generation 002
      │
      ├── Load objective
      ├── Load verified handoff
      ├── Read relevant files
      ├── Continue exact next step
      │
      └── Compact Handoff
               │
               ▼
              ...
```

The guiding principle is:

> **Remember information only when remembering it is cheaper than rediscovering it.**

---

## What the Handoff Contains

Before a generation terminates, it should preserve only information useful to its successor.

Examples include:

- current objective
- verified progress
- modified files
- test results
- important discoveries
- failed approaches
- approaches that should not be repeated
- unresolved problems
- relevant files
- exact next action
- completion criteria

The complete previous conversation does not need to be inherited.

---

## Fresh Context Architecture

A conventional autonomous loop may behave like this:

```text
Run 1
  ↓
Context grows
  ↓
Run 2
  ↓
Context grows
  ↓
Run 3
  ↓
Context grows
  ↓
...
```

A generational architecture behaves differently:

```text
Run 1
  ↓
Handoff
  ↓
Context ends

Run 2
  ↓
Handoff
  ↓
Context ends

Run 3
  ↓
Handoff
  ↓
Context ends
```

The key is not simply clearing context.

The key is creating a **high-quality transition before the context disappears**.

---

## External Verification

Autonomous agents should not be trusted purely because they say a task is complete.

SkillQuarry favors independent verification whenever possible.

```text
Agent reports COMPLETE
          │
          ▼
 Independent verification
          │
      ┌───┴───┐
      │       │
    PASS     FAIL
      │       │
      ▼       ▼
   Finish   Continue
```

For coding tasks, independent verification may include:

- tests
- linting
- builds
- type checking
- static analysis
- security checks
- expected file changes
- custom validation commands

A model's completion statement should never override a failing verification step.

---

# Reliability

Long-running autonomous workflows should be designed for failure.

Potential protections include:

- atomic state writes
- handoff validation
- interrupted-run recovery
- corrupted-state detection
- false-completion protection
- stalled-loop detection
- maximum generation limits
- maximum turn limits
- process timeouts
- token limits
- cost limits
- concurrent-run locks
- bounded context injection
- bounded Git output
- external verification

Safety should be enforced by orchestration whenever possible instead of relying entirely on the model to remember instructions.

---

# Security

Agent skills must be treated as **executable capabilities**, not harmless text.

Depending on their design, a skill may cause an agent to:

- execute shell commands
- modify source files
- inspect repositories
- install packages
- access external APIs
- read environment variables
- perform Git operations
- communicate over a network

Users should inspect third-party skills before execution.

SkillQuarry's planned security model includes:

- explicit permission manifests
- source checksums
- dependency inspection
- secret scanning
- static analysis
- command auditing
- signed releases
- reproducible packaging
- security advisories
- transparent installation behavior
- community reporting

---

# Skill Quality

A marketplace is only useful when users can evaluate quality.

SkillQuarry plans to introduce objective validation levels.

| Level | Meaning |
|---|---|
| Experimental | Early-stage capability |
| Verified | Structure and metadata validated |
| Tested | Automated tests available |
| Trusted | Reproducible testing and security checks |
| Certified | Highest SkillQuarry validation level |

These levels are planned and are not yet implemented.

---

# Testing Philosophy

A skill should not be considered reliable because its author says it works.

It should demonstrate that it works.

SkillQuarry encourages progressively harder testing.

### Level 1 — Beginner

Verify the simplest intended workflow.

### Level 2 — Everyday Developer

Test realistic multi-step usage.

### Level 3 — Advanced

Introduce failures and verify recovery.

### Level 4 — Expert

Ensure independent verification can reject incorrect agent conclusions.

### Level 5 — Adversarial

Test malformed state, infinite loops, interrupted processes, pathological input, and resource exhaustion.

---

# Planned Repository Structure

As the project grows, SkillQuarry may evolve toward a structure similar to:

```text
SkillQuarry/
│
├── skills/
│   ├── autonomous/
│   ├── coding/
│   ├── testing/
│   ├── security/
│   ├── ui-ux/
│   ├── devops/
│   ├── mobile/
│   └── utilities/
│
├── registry/
│   ├── skills.json
│   └── schema.json
│
├── adapters/
│   ├── claude-code/
│   ├── codex/
│   └── generic/
│
├── cli/
├── tests/
├── docs/
│
├── .github/
│   ├── workflows/
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
│
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
├── LICENSE
└── README.md
```

This is a target architecture and does not imply that every directory currently exists.

---

# Planned CLI

The long-term SkillQuarry experience is intended to resemble a package manager.

### Search

```bash
skillquarry search testing
```

### Inspect

```bash
skillquarry info ralph-generational-handoff
```

### Install

```bash
skillquarry install ralph-generational-handoff
```

### Validate

```bash
skillquarry validate ./my-skill
```

### Update

```bash
skillquarry update
```

### Diagnose

```bash
skillquarry doctor
```

These commands describe the intended interface and may not yet be implemented.

---

# Roadmap

## Phase 1 — Foundation

- [x] Create SkillQuarry repository
- [x] Define project vision
- [x] Choose Apache License 2.0
- [x] Define initial marketplace concept
- [x] Design Ralph Generational Handoff concept
- [ ] Finalize the SkillQuarry skill specification
- [ ] Add machine-readable schema
- [ ] Add contribution guidelines
- [ ] Add security policy
- [ ] Add code of conduct
- [ ] Add CI validation

## Phase 2 — First Skills

- [ ] Add Ralph Generational Handoff
- [ ] Add automated skill tests
- [ ] Add example skills
- [ ] Add compatibility metadata
- [ ] Add permission metadata
- [ ] Add skill validation

## Phase 3 — Registry

- [ ] Build skill registry
- [ ] Add semantic versioning
- [ ] Add category system
- [ ] Add checksums
- [ ] Add compatibility filtering
- [ ] Add automated validation
- [ ] Add security metadata

## Phase 4 — CLI

- [ ] Implement search
- [ ] Implement skill information
- [ ] Implement installation
- [ ] Implement updates
- [ ] Implement validation
- [ ] Implement diagnostics

## Phase 5 — Marketplace

- [ ] Web marketplace
- [ ] Search and filtering
- [ ] Skill detail pages
- [ ] Maintainer profiles
- [ ] Version history
- [ ] Compatibility information
- [ ] Security information
- [ ] Install statistics
- [ ] Community discovery

## Phase 6 — Ecosystem

- [ ] Signed skill packages
- [ ] Skill dependencies
- [ ] Skill composition
- [ ] Community verification
- [ ] Automatic agent discovery
- [ ] Remote registries
- [ ] Private registries
- [ ] Enterprise support
- [ ] Public registry API

---

# Contributing

SkillQuarry is intended to become a community-driven open-source project.

Contributions may include:

- new skills
- agent adapters
- test infrastructure
- registry development
- CLI development
- security tooling
- marketplace development
- documentation
- schema improvements
- bug fixes
- feature proposals

Until a dedicated `CONTRIBUTING.md` exists, contributions can be proposed through GitHub Issues and Pull Requests.

---

## Creating a Skill

A high-quality skill contribution should explain:

1. What the skill does.
2. Which agents it supports.
3. Which permissions it requires.
4. Whether it executes external commands.
5. Which files or services it accesses.
6. How it was tested.
7. Which limitations are known.
8. Which license applies.

Security-sensitive behavior should never be hidden.

---

# Community

If SkillQuarry is useful to you, you can help by:

- ⭐ starring the repository
- 🍴 forking the project
- 🧠 contributing a skill
- 🐛 reporting bugs
- 💡 suggesting features
- 🔐 reporting security issues responsibly
- 🤝 contributing code or documentation

---

## Star History

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=BEKO2210/SkillQuarry&type=Date)](https://star-history.com/#BEKO2210/SkillQuarry&Date)

</div>

---

## Contributors

<div align="center">

<a href="https://github.com/BEKO2210/SkillQuarry/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=BEKO2210/SkillQuarry" alt="SkillQuarry contributors">
</a>

</div>

---

# License

SkillQuarry is licensed under the **Apache License 2.0**.

See [LICENSE](LICENSE) for the complete license text.

Individual third-party skills may use different compatible licenses.

Always inspect the license declared by a skill before redistribution or commercial use.

---

# Disclaimer

SkillQuarry is an independent open-source project.

Claude, Claude Code, OpenAI, Codex, Gemini, GitHub, MCP, and other product or company names are trademarks of their respective owners.

They are referenced only to describe interoperability or intended compatibility.

SkillQuarry is not affiliated with or endorsed by those companies unless explicitly stated otherwise.

AI agents may execute commands, modify files, install software, or interact with external systems.

**Always review third-party skills and their permissions before execution.**

---

<div align="center">

# ⛏️ SkillQuarry

### Build capabilities once. Share intelligence everywhere.

<br>

[![GitHub](https://img.shields.io/badge/GitHub-BEKO2210%2FSkillQuarry-181717?style=for-the-badge&logo=github)](https://github.com/BEKO2210/SkillQuarry)

<br>

**Open skills. Open agents. Open ecosystem.**

<br>

If you believe reusable agent capabilities should be open, portable, inspectable, and testable, give SkillQuarry a ⭐.

</div>


