<div align="center">

# ⛏️ SkillQuarry

### The open marketplace for agent skills.

**Discover, build, test, share, and install reusable capabilities for AI coding agents.**

<br />

[![GitHub Stars](https://img.shields.io/github/stars/BEKO2210/SkillQuarry?style=for-the-badge&logo=github&label=Stars)](https://github.com/BEKO2210/SkillQuarry/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/BEKO2210/SkillQuarry?style=for-the-badge&logo=github&label=Forks)](https://github.com/BEKO2210/SkillQuarry/network/members)
[![GitHub Issues](https://img.shields.io/github/issues/BEKO2210/SkillQuarry?style=for-the-badge&logo=github)](https://github.com/BEKO2210/SkillQuarry/issues)
[![GitHub Pull Requests](https://img.shields.io/github/issues-pr/BEKO2210/SkillQuarry?style=for-the-badge&logo=github)](https://github.com/BEKO2210/SkillQuarry/pulls)
[![License](https://img.shields.io/github/license/BEKO2210/SkillQuarry?style=for-the-badge)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/BEKO2210/SkillQuarry?style=for-the-badge&logo=git)](https://github.com/BEKO2210/SkillQuarry/commits/main)

<br />

[**Why SkillQuarry?**](#why-skillquarry) ·
[**Marketplace**](#skill-marketplace) ·
[**Skill Standard**](#skill-standard) ·
[**Ralph GH**](#ralph-generational-handoff) ·
[**Roadmap**](#roadmap) ·
[**Contributing**](#contributing)

<br />

> **Build capabilities once. Share intelligence everywhere.**

</div>

---

## What is SkillQuarry?

**SkillQuarry** is an open-source ecosystem for reusable AI-agent skills.

AI coding agents are becoming increasingly capable, but much of their useful behavior still lives inside giant prompts, private configuration files, shell scripts, hooks, isolated repositories, and undocumented workflows.

SkillQuarry aims to turn those capabilities into **small, portable, inspectable, testable, and versioned components**.

A SkillQuarry skill may teach an agent how to:

- debug an application
- review a pull request
- perform a security audit
- improve UI and UX
- run tests and diagnose failures
- manage releases
- optimize context usage
- orchestrate autonomous coding loops
- recover from interrupted work
- generate documentation
- inspect repositories
- perform Android workflows
- automate DevOps operations
- coordinate multiple specialized agents

The goal is to make agent capabilities reusable instead of repeatedly rebuilding the same prompt logic from scratch.

---

## Why SkillQuarry?

Today, powerful agent workflows are fragmented across:

- `SKILL.md` files
- system prompts
- Claude Code plugins
- hooks
- MCP integrations
- shell scripts
- GitHub repositories
- local configuration
- custom agent frameworks
- private automation setups

SkillQuarry provides a common place to **discover, understand, test, and distribute** these capabilities.

Every high-quality SkillQuarry skill should aim to be:

**Discoverable · Portable · Inspectable · Testable · Versioned · Composable · Secure**

---

## Vision

The future of AI development is unlikely to be one enormous agent that knows everything.

Instead, agents can become more capable by dynamically combining **small specialized skills**.

SkillQuarry is designed around a simple idea:

> **A package ecosystem for agent capabilities.**

Similar to how developers install reusable software libraries instead of rewriting everything themselves, AI agents should be able to reuse well-defined capabilities.

The long-term experience should feel as simple as:

```bash
skillquarry search security
skillquarry install repository-auditor
skillquarry update

The implementation of the SkillQuarry CLI and registry is part of the project roadmap.

---

Vendor Neutral

SkillQuarry is intentionally designed not to depend on a single AI provider.

The ecosystem can support skills and adapters for environments such as:

<div align="center">"Claude Code" (https://img.shields.io/badge/Claude_Code-Target-191919?style=for-the-badge)
"Codex" (https://img.shields.io/badge/Codex-Target-191919?style=for-the-badge)
"Gemini" (https://img.shields.io/badge/Gemini-Target-191919?style=for-the-badge)
"MCP" (https://img.shields.io/badge/MCP-Target-191919?style=for-the-badge)

</div>Compatibility always depends on the individual skill and its declared requirements.

SkillQuarry does not imply endorsement by any AI provider or platform.

---

Skill Marketplace

SkillQuarry is intended to grow into a searchable open marketplace of agent capabilities.

Potential categories include:

Category| Examples
🧠 Agent Intelligence| Planning, context management, handoffs
💻 Coding| Debugging, refactoring, migrations
🧪 Testing| Unit tests, integration tests, E2E
🔐 Security| Auditing, hardening, dependency analysis
🎨 UI / UX| Accessibility, responsive design, design review
📦 DevOps| CI/CD, deployment, Docker, releases
📱 Mobile| Android, iOS, store workflows
🌐 Web| Frontend, backend, APIs, performance
📚 Documentation| README files, architecture, API docs
🤖 Autonomous Agents| Ralph loops, repair agents, orchestration
🔌 Integrations| MCP, hooks, APIs
🛠️ Utilities| Git, repository analysis, automation

The marketplace itself is under development.

---

Skill Standard

A SkillQuarry skill should be understandable without requiring the user to reverse-engineer it.

A mature skill package may contain:

my-skill/
├── SKILL.md
├── skill.json
├── README.md
├── tests/
├── examples/
├── hooks/
└── scripts/

Not every skill needs every directory.

The exact SkillQuarry specification is still being developed.

---

Suggested Skill Metadata

A skill manifest should eventually describe information such as:

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

Future versions of the schema may additionally declare:

- required tools
- filesystem access
- network access
- shell execution
- supported operating systems
- supported agent environments
- dependencies
- permissions
- checksums
- test status
- maintainer information

---

Ralph Generational Handoff

One of the first concepts being developed for SkillQuarry is Ralph Generational Handoff.

Fresh context. Persistent progress. Controlled autonomy.

Traditional autonomous agent loops may continue working inside an increasingly large conversation context.

Over long-running tasks this can create several problems:

- unnecessary context growth
- repeated token processing
- irrelevant historical information
- degraded focus
- higher cost
- difficult crash recovery
- uncontrolled autonomous loops

Ralph Generational Handoff explores a different architecture.

Each generation performs useful work, produces a compact verified handoff, and then terminates.

The next generation starts with a fresh context and receives only the information required to continue.

Generation 001
      │
      ├── Work
      ├── Test
      ├── Verify
      │
      └── Compact Handoff
               │
               ▼
        Fresh Context
               │
               ▼
Generation 002
      │
      ├── Load Objective
      ├── Load Handoff
      ├── Read Relevant Files
      ├── Continue Work
      │
      └── Compact Handoff
               │
               ▼
              ...

The guiding principle is:

«Remember information only when remembering it is cheaper than rediscovering it.»

---

Generational Handoff

Before a generation ends, it should leave its successor a concise state containing only information useful for continuing the task.

Typical handoff information includes:

- primary objective
- verified progress
- modified files
- test status
- important discoveries
- failed approaches
- approaches that should not be repeated
- unresolved problems
- files to inspect next
- exact next action
- completion criteria

The full previous conversation does not need to be carried forward.

---

Why Fresh Context?

Consider a long autonomous task.

A traditional loop can look like:

Run 1 → Context grows
Run 2 → Context grows
Run 3 → Context grows
Run 4 → Context grows
...

A generational architecture instead looks like:

Run 1 → Handoff → Context ends
Run 2 → Handoff → Context ends
Run 3 → Handoff → Context ends
...

The goal is not simply to erase context.

The important part is creating a high-quality transition before context is discarded.

Without that transition, the next generation might waste resources rediscovering everything.

---

Reliability Principles

Long-running autonomous agents should not be trusted purely because they claim they succeeded.

SkillQuarry favors external verification whenever possible.

For example:

Agent says COMPLETE
        │
        ▼
Independent verification
        │
   ┌────┴────┐
   │         │
 PASS       FAIL
   │         │
 Finish    Continue

A completion statement should not override failing tests.

---

Safety Goals

Robust autonomous skills should protect against problems such as:

- incomplete handoffs
- corrupted state
- interrupted processes
- false completion claims
- repeated failed approaches
- infinite loops
- runaway token usage
- runaway cost
- process timeouts
- multiple concurrent runners
- excessively large context injection
- destructive repository operations

Where possible, safety should be enforced by the orchestration layer rather than relying only on the model to remember instructions.

---

Skill Quality

A marketplace becomes valuable only when users can evaluate whether a skill is trustworthy.

SkillQuarry plans to introduce quality levels based on objective validation.

Level| Meaning
Experimental| Early-stage capability
Verified| Structure and metadata validated
Tested| Automated tests available
Trusted| Reproducible testing and security checks
Certified| Highest SkillQuarry quality standard

These levels are planned and are not yet implemented.

---

Future Skill Information

Marketplace listings may eventually expose:

- name
- description
- version
- author
- license
- compatibility
- permissions
- dependencies
- required tools
- source repository
- checksum
- test status
- security status
- supported platforms
- version history
- installation instructions

This gives users information before allowing an agent skill to execute.

---

Security

Agent skills must be treated as executable capabilities, not harmless text files.

Depending on their design, they may instruct an agent to:

- execute shell commands
- modify files
- access repositories
- communicate with external services
- read environment variables
- interact with APIs
- install dependencies
- perform Git operations

Users should always review third-party skills before execution.

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

Security work is part of the ongoing roadmap.

---

Testing Philosophy

A skill should not be considered reliable simply because its creator says it works.

It should demonstrate that it works.

SkillQuarry encourages testing from simple scenarios through adversarial failure cases.

Level 1 — Beginner

Verify the simplest intended workflow.

Level 2 — Everyday Developer

Test realistic multi-step usage.

Level 3 — Advanced

Introduce failures and verify recovery.

Level 4 — Expert

Verify that independent checks can reject incorrect agent conclusions.

Level 5 — Adversarial

Test loops, malformed state, interruptions, pathological input, and resource exhaustion.

---

Design Principles

Open by Default

Skills should be inspectable whenever possible.

Vendor Neutral

The ecosystem should not be controlled by one AI provider.

Local First

Capabilities should work locally whenever reasonable.

Explicit Permissions

Users should understand what a skill can access.

Composable

Small specialized skills should be able to work together.

Testable

Agent behavior should be measurable.

Reproducible

A specific skill version should behave as predictably as practical.

Transparent

Installation and executable behavior should not be hidden.

Fail Safely

When uncertain, autonomous workflows should prefer stopping over destructive guessing.

---

Planned Repository Structure

As SkillQuarry grows, the repository may evolve toward a structure similar to:

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

This is a target architecture, not a claim that every directory currently exists.

---

Planned CLI

The future SkillQuarry CLI is intended to provide a package-manager-like experience.

Search

skillquarry search testing

Inspect

skillquarry info ralph-generational-handoff

Install

skillquarry install ralph-generational-handoff

Validate

skillquarry validate ./my-skill

Update

skillquarry update

Diagnose

skillquarry doctor

These commands describe the planned interface and may not yet be implemented.

---

Roadmap

Phase 1 — Foundation

- [x] Create SkillQuarry repository
- [x] Define project vision
- [x] Choose Apache 2.0 license
- [x] Define initial marketplace concept
- [x] Design Ralph Generational Handoff concept
- [ ] Finalize SkillQuarry skill specification
- [ ] Add machine-readable schema
- [ ] Add contribution guidelines
- [ ] Add security policy
- [ ] Add code of conduct
- [ ] Add CI validation

Phase 2 — First Skills

- [ ] Add Ralph Generational Handoff
- [ ] Add automated skill tests
- [ ] Add example skills
- [ ] Add compatibility metadata
- [ ] Add permission metadata
- [ ] Add skill validation

Phase 3 — Registry

- [ ] Build skill registry
- [ ] Add semantic versioning
- [ ] Add category system
- [ ] Add checksums
- [ ] Add compatibility filtering
- [ ] Add automated validation
- [ ] Add security metadata

Phase 4 — CLI

- [ ] "skillquarry search"
- [ ] "skillquarry info"
- [ ] "skillquarry install"
- [ ] "skillquarry update"
- [ ] "skillquarry validate"
- [ ] "skillquarry doctor"

Phase 5 — Marketplace

- [ ] Web marketplace
- [ ] Search and filtering
- [ ] Skill detail pages
- [ ] Maintainer profiles
- [ ] Version history
- [ ] Compatibility information
- [ ] Security information
- [ ] Install statistics
- [ ] Community discovery

Phase 6 — Ecosystem

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

Contributing

SkillQuarry is intended to become a community-driven project.

Future contributions may include:

- new skills
- testing infrastructure
- agent adapters
- registry development
- CLI development
- security tooling
- documentation
- marketplace development
- schema design
- bug fixes
- feature proposals

Until a dedicated "CONTRIBUTING.md" is added, contributors can use GitHub Issues and Pull Requests to propose improvements.

---

Creating a Skill

A good contribution should clearly explain:

1. What the skill does.
2. Which agents or environments it supports.
3. Which permissions it requires.
4. Whether it executes external commands.
5. Which files or services it may access.
6. How it was tested.
7. Which limitations are known.
8. Which license applies.

Security-sensitive behavior should never be hidden.

---

Community

If you find the project useful, you can help by:

- ⭐ starring the repository
- 🍴 forking the project
- 🧠 contributing a skill
- 🐛 reporting bugs
- 💡 suggesting features
- 🔐 reporting security problems responsibly
- 🤝 contributing code or documentation

---

Star History

<div align="center">""Star History Chart" (https://api.star-history.com/svg?repos=BEKO2210/SkillQuarry&type=Date)" (https://star-history.com/#BEKO2210/SkillQuarry&Date)

</div>---

Contributors

<div align="center"><a href="https://github.com/BEKO2210/SkillQuarry/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=BEKO2210/SkillQuarry" alt="SkillQuarry contributors" />
</a></div>---

License

SkillQuarry is licensed under the Apache License 2.0.

See "LICENSE" (LICENSE) for the full license text.

Individual third-party skills added to the ecosystem may use different compatible licenses. Always inspect the license declared by a skill before redistribution or commercial use.

---

Disclaimer

SkillQuarry is an independent open-source project.

Names such as Claude, Claude Code, Codex, Gemini, GitHub, MCP, and other trademarks belong to their respective owners and are referenced solely for compatibility and descriptive purposes.

SkillQuarry is not affiliated with or endorsed by those companies unless explicitly stated.

AI agents can execute commands, modify files, install software, and interact with external systems.

Always review third-party skills and their permissions before execution.

---

<div align="center"><br />⛏️ SkillQuarry

Build capabilities once. Share intelligence everywhere.

<br />""Repository" (https://img.shields.io/badge/GitHub-BEKO2210%2FSkillQuarry-181717?style=for-the-badge&logo=github)" (https://github.com/BEKO2210/SkillQuarry)

<br />Open skills. Open agents. Open ecosystem.

<br />If you want to help build an open marketplace for reusable agent intelligence, give SkillQuarry a ⭐.

</div>
```
