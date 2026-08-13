<div align="center">

<img src="docs/assets/skillquarry-logo.svg" alt="SkillQuarry" width="120" />

# SkillQuarry

### The open marketplace for agent skills.

**Discover, install, build, test, and share reusable skills for AI coding agents.**

[![GitHub Stars](https://img.shields.io/github/stars/YOUR_USERNAME/skillquarry?style=for-the-badge&logo=github&label=Stars)](https://github.com/YOUR_USERNAME/skillquarry/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/YOUR_USERNAME/skillquarry?style=for-the-badge&logo=github&label=Forks)](https://github.com/YOUR_USERNAME/skillquarry/network/members)
[![GitHub Issues](https://img.shields.io/github/issues/YOUR_USERNAME/skillquarry?style=for-the-badge&logo=github)](https://github.com/YOUR_USERNAME/skillquarry/issues)
[![GitHub Pull Requests](https://img.shields.io/github/issues-pr/YOUR_USERNAME/skillquarry?style=for-the-badge&logo=github)](https://github.com/YOUR_USERNAME/skillquarry/pulls)

[![CI](https://img.shields.io/github/actions/workflow/status/YOUR_USERNAME/skillquarry/ci.yml?branch=main&style=for-the-badge&label=CI&logo=githubactions)](https://github.com/YOUR_USERNAME/skillquarry/actions)
[![Security](https://img.shields.io/badge/Security-Policy-success?style=for-the-badge&logo=shield)](SECURITY.md)
[![License](https://img.shields.io/github/license/YOUR_USERNAME/skillquarry?style=for-the-badge)](LICENSE)
[![Latest Release](https://img.shields.io/github/v/release/YOUR_USERNAME/skillquarry?style=for-the-badge&logo=github)](https://github.com/YOUR_USERNAME/skillquarry/releases)
[![Last Commit](https://img.shields.io/github/last-commit/YOUR_USERNAME/skillquarry?style=for-the-badge&logo=git)](https://github.com/YOUR_USERNAME/skillquarry/commits/main)

<br />

[**Explore Skills**](#-skill-marketplace) ·
[**Quick Start**](#-quick-start) ·
[**Build a Skill**](#-build-a-skill) ·
[**Ralph GH**](#-ralph-generational-handoff) ·
[**Contribute**](#-contributing)

<br />

<img src="docs/assets/skillquarry-demo.gif" alt="SkillQuarry demo" width="900" />

<br />

> **One repository. One open standard. An ecosystem of reusable intelligence.**

</div>

---

## What is SkillQuarry?

**SkillQuarry** is an open ecosystem and marketplace for reusable AI-agent skills.

Instead of writing the same instructions, workflows, hooks, prompts, and automation logic again and again, SkillQuarry turns them into portable, testable, versioned building blocks.

A SkillQuarry skill can teach an agent how to:

- debug a production application
- review a pull request
- design a modern interface
- perform security analysis
- optimize context usage
- orchestrate autonomous coding loops
- test an Android application
- audit a repository
- generate documentation
- perform release engineering
- coordinate multiple agents
- recover from failed autonomous runs
- and much more

SkillQuarry is designed to become a **vendor-neutral home for agent capabilities**.

<br />

<div align="center">

**Claude Code · Codex · Gemini · Agent Frameworks · Hooks · MCP · CLI Tools · Autonomous Workflows**

</div>

---

## Why SkillQuarry?

Modern coding agents are incredibly capable, but useful agent behavior is still scattered across:

- giant prompts
- private dotfiles
- shell scripts
- GitHub gists
- custom hooks
- undocumented workflows
- isolated repositories
- proprietary agent configurations

SkillQuarry gives these capabilities a home.

Every skill should be:

**Discoverable. Portable. Inspectable. Testable. Versioned. Composable.**

---

## Vision

We believe the future of AI development is not one giant agent.

It is an ecosystem of **small, specialized, reusable capabilities** that agents can discover and combine dynamically.

Think of SkillQuarry as:

> **npm for agent capabilities.**

or:

> **A package registry for intelligence.**

The long-term goal is simple:

**Install a capability as easily as you install a software package.**

---

## Skill Marketplace

<div align="center">

<img src="docs/assets/marketplace.gif" alt="SkillQuarry Marketplace" width="900" />

</div>

SkillQuarry is designed around a searchable skill catalog.

| Category | Examples |
|---|---|
| 🧠 Agent Intelligence | Planning, reasoning workflows, handoffs |
| 💻 Coding | Refactoring, migrations, debugging |
| 🧪 Testing | Unit, integration, E2E, regression |
| 🔐 Security | Auditing, dependency analysis, hardening |
| 🎨 UI / UX | Design review, accessibility, responsive UI |
| 📦 DevOps | CI/CD, Docker, releases, deployment |
| 📱 Mobile | Android, iOS, Play Store workflows |
| 🌐 Web | Frontend, backend, APIs, performance |
| 📚 Documentation | README, API docs, architecture |
| 🤖 Autonomous Agents | Ralph loops, repair agents, orchestration |
| 🔌 Integrations | MCP, hooks, APIs, external tools |
| 🛠️ Utilities | Git, repository inspection, automation |

---

## Featured Skill

# Ralph Generational Handoff

> **Fresh context. Persistent progress. Controlled autonomy.**

Traditional autonomous agent loops can accumulate enormous amounts of conversational context over time.

Ralph Generational Handoff approaches the problem differently.

Each generation receives a **fresh context** while inheriting only the smallest useful verified handoff from the previous generation.

<div align="center">

<img src="docs/assets/ralph-generational-handoff.gif" alt="Ralph Generational Handoff" width="860" />

</div>

### How it works

```text
Generation 001
      │
      ├── Work
      ├── Test
      ├── Verify
      │
      └── Create compact handoff
               │
               ▼
        Context terminates
               │
               ▼
Generation 002
      │
      ├── Load objective
      ├── Load verified handoff
      ├── Read only relevant files
      ├── Continue exact next action
      │
      └── Create next handoff
               │
               ▼
              ...

Why?

Because repeatedly carrying an entire conversation forward can become expensive and noisy.

Ralph GH instead follows one principle:

«Remember information only when remembering it is cheaper than rediscovering it.»

Safety mechanisms

Ralph GH includes protections for:

- atomic handoff writes
- interrupted generations
- invalid state
- false completion claims
- stalled loops
- runaway token usage
- process timeouts
- dirty repositories
- duplicate runners
- external verification
- bounded handoff sizes
- bounded Git context
- generation limits
- turn limits
- optional cost limits

---

Architecture

                         ┌───────────────────────┐
                         │      SkillQuarry      │
                         │       Registry        │
                         └───────────┬───────────┘
                                     │
                   ┌─────────────────┼─────────────────┐
                   │                 │                 │
                   ▼                 ▼                 ▼
             ┌───────────┐     ┌───────────┐     ┌───────────┐
             │   Skill   │     │   Skill   │     │   Skill   │
             │     A     │     │     B     │     │     C     │
             └─────┬─────┘     └─────┬─────┘     └─────┬─────┘
                   │                 │                 │
                   └─────────────────┼─────────────────┘
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │    Agent Adapter      │
                         └───────────┬───────────┘
                                     │
                      ┌──────────────┼──────────────┐
                      ▼              ▼              ▼
                Claude Code       Codex         Others

---

Repository Structure

skillquarry/
│
├── skills/
│   ├── autonomous/
│   │   └── ralph-generational-handoff/
│   │
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
│
├── tests/
│
├── docs/
│   └── assets/
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

---

Quick Start

Clone SkillQuarry:

git clone https://github.com/YOUR_USERNAME/skillquarry.git
cd skillquarry

Explore available skills:

ls skills

Open a skill:

cd skills/autonomous/ralph-generational-handoff

Read its documentation and installation instructions.

---

Planned CLI

The long-term SkillQuarry experience is designed to feel like a package manager.

Search

skillquarry search testing

Inspect

skillquarry info ralph-generational-handoff

Install

skillquarry install ralph-generational-handoff

Update

skillquarry update

List installed skills

skillquarry list

Validate a skill

skillquarry validate ./my-skill

---

Build a Skill

A SkillQuarry skill should be self-contained and easy to inspect.

Example:

my-skill/
│
├── SKILL.md
├── skill.json
├── README.md
├── tests/
├── hooks/
├── scripts/
└── examples/

Minimal metadata

{
  "name": "my-skill",
  "version": "1.0.0",
  "description": "A reusable capability for AI coding agents.",
  "category": "coding",
  "license": "MIT",
  "compatibility": [
    "claude-code",
    "codex"
  ]
}

---

Skill Quality Standard

A marketplace is only useful if users can trust what they install.

SkillQuarry aims to grade skills using automated checks.

Proposed quality levels

Level| Meaning
🟤 Experimental| Early prototype
⚪ Verified| Schema and structure validated
🟡 Tested| Automated tests included
🟢 Trusted| Reproducible test suite and security review
💎 Certified| Highest SkillQuarry quality level

Every published skill can eventually expose:

- version
- compatibility
- permissions
- required tools
- test status
- security status
- maintainer
- license
- last update
- install count
- rating
- source integrity
- checksum

---

Security First

Agent skills can execute powerful workflows.

SkillQuarry therefore treats skills as code, not harmless text.

Before installing a third-party skill, users should be able to inspect exactly what it can access and execute.

Planned protections include:

- permission manifests
- command allowlists
- source checksums
- signed releases
- reproducible packages
- dependency inspection
- static analysis
- secret scanning
- malicious prompt detection
- sandbox compatibility
- transparent install scripts
- community reporting
- security advisories

Please report vulnerabilities according to "SECURITY.md" (SECURITY.md).

---

Testing Philosophy

A skill should not be considered reliable because its author says it works.

It should prove it.

SkillQuarry encourages testing at multiple levels:

Level 1 — Beginner

Does the skill work for the simplest intended use case?

Level 2 — Everyday Developer

Does it work through multiple realistic operations?

Level 3 — Advanced

Does it recover when something unexpected fails?

Level 4 — Expert

Does independent verification detect incorrect agent conclusions?

Level 5 — Adversarial / Pro

Does the system remain safe under loops, malformed state, interruptions, and pathological inputs?

---

Marketplace Principles

SkillQuarry is being designed around several non-negotiable principles.

Open by default

Skills should be inspectable.

Vendor neutral

The ecosystem should not depend on one AI provider.

Local first

A skill should work locally whenever possible.

Explicit permissions

Users should know what a skill can access before running it.

Composable

Small skills should work together.

Testable

Agent behavior should be measurable.

Reproducible

The same skill version should behave predictably.

No black boxes

Installation logic and executable components should remain visible.

---

Compatibility

<div align="center">"Claude Code" (https://img.shields.io/badge/Claude_Code-Compatible-191919?style=for-the-badge)
"Codex" (https://img.shields.io/badge/Codex-Planned-191919?style=for-the-badge)
"Gemini" (https://img.shields.io/badge/Gemini-Planned-191919?style=for-the-badge)
"MCP" (https://img.shields.io/badge/MCP-Compatible-191919?style=for-the-badge)
"Linux" (https://img.shields.io/badge/Linux-Supported-191919?style=for-the-badge&logo=linux)
"macOS" (https://img.shields.io/badge/macOS-Planned-191919?style=for-the-badge&logo=apple)
"Windows" (https://img.shields.io/badge/Windows-Planned-191919?style=for-the-badge&logo=windows)

</div>«Compatibility badges describe SkillQuarry support targets and do not imply endorsement by the respective vendors.»

---

Roadmap

Phase 1 — Foundation

- [x] Define SkillQuarry concept
- [x] Design generational agent architecture
- [x] Build first autonomous skill
- [x] Add crash recovery
- [x] Add independent verification
- [x] Add stall detection
- [ ] Finalize skill specification
- [ ] Add JSON schema
- [ ] Add repository CI

Phase 2 — Registry

- [ ] Searchable skill registry
- [ ] Semantic versioning
- [ ] Compatibility metadata
- [ ] Skill validation
- [ ] Checksums
- [ ] Automated test badges
- [ ] Category system

Phase 3 — CLI

- [ ] "skillquarry search"
- [ ] "skillquarry install"
- [ ] "skillquarry update"
- [ ] "skillquarry validate"
- [ ] "skillquarry doctor"
- [ ] Agent adapters

Phase 4 — Marketplace

- [ ] Web marketplace
- [ ] Skill pages
- [ ] Search and filtering
- [ ] Maintainer profiles
- [ ] Ratings
- [ ] Install analytics
- [ ] Version history
- [ ] Security information

Phase 5 — Ecosystem

- [ ] Signed skill packages
- [ ] Community verification
- [ ] Skill dependencies
- [ ] Skill composition
- [ ] Automatic agent discovery
- [ ] Remote registries
- [ ] Enterprise registries
- [ ] Public SkillQuarry API

---

Example Future Experience

Imagine opening a repository and telling your agent:

«Find and install the best verified security audit skill.»

The agent searches SkillQuarry, evaluates compatibility and permissions, installs the selected skill, executes it, verifies the results, and records exactly what happened.

That is the direction.

---

Contributing

SkillQuarry is intended to be community-driven.

Contributions are welcome for:

- new skills
- adapters
- testing infrastructure
- security improvements
- documentation
- CLI development
- marketplace development
- schema design
- bug fixes
- ideas

Please read "CONTRIBUTING.md" (CONTRIBUTING.md) before opening a pull request.

---

Adding Your Skill

1. Fork this repository.
2. Create a directory in the appropriate category.
3. Add your "SKILL.md".
4. Add metadata.
5. Add tests.
6. Run the validator.
7. Open a pull request.

Every submission should clearly explain:

- what the skill does
- which agents it supports
- what permissions it needs
- whether it runs external commands
- how it was tested
- known limitations

---

Community

If SkillQuarry becomes useful to you:

⭐ Star the repository
🍴 Fork it
🧠 Build a skill
🐛 Report problems
🔐 Report security issues responsibly
🤝 Contribute improvements

Every contribution helps build a more open agent ecosystem.

---

Star History

<div align="center">""Star History Chart" (https://api.star-history.com/svg?repos=YOUR_USERNAME/skillquarry&type=Date)" (https://star-history.com/#YOUR_USERNAME/skillquarry&Date)

</div>---

Contributors

<div align="center"><a href="https://github.com/YOUR_USERNAME/skillquarry/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=YOUR_USERNAME/skillquarry" alt="SkillQuarry contributors" />
</a></div>---

Support the Project

The best way to support SkillQuarry right now is simple:

Star the repository and build something useful with it.

If this project grows, additional sponsorship and maintainer programs may be introduced later.

---

License

SkillQuarry is released under the terms defined in the repository's "LICENSE" (LICENSE) file.

Individual community skills may declare their own compatible licenses.

Always check a skill's metadata before redistribution or commercial use.

---

Disclaimer

SkillQuarry is an independent open-source project.

References to Claude, Claude Code, Codex, Gemini, MCP, GitHub, or other products and trademarks are used only to describe compatibility.

SkillQuarry is not endorsed by or affiliated with the respective trademark owners unless explicitly stated otherwise.

AI agents can modify files, execute commands, and interact with external systems.

Always review permissions and third-party skills before execution.

---

<div align="center"><br /><img src="docs/assets/skillquarry-logo.svg" width="72" alt="SkillQuarry" />SkillQuarry

Build capabilities once. Share intelligence everywhere.

<br />"Report Bug" (https://github.com/YOUR_USERNAME/skillquarry/issues/new?template=bug_report.yml)
·
"Request Feature" (https://github.com/YOUR_USERNAME/skillquarry/issues/new?template=feature_request.yml)
·
"Contribute" (CONTRIBUTING.md)

<br />If you believe reusable agent skills should be open, portable, and testable — give SkillQuarry a ⭐.

</div>
```
