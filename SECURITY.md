# Security Policy

SkillQuarry distributes **executable capabilities**. A skill can run shell
commands, modify files, and drive an AI agent that does both. Security reports
are treated accordingly.

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Use GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/BEKO2210/SkillQuarry/security/advisories/new).
It is private to the maintainers until an advisory is published, and it keeps the
report, the fix and the disclosure in one place.

A useful report contains:

- the affected skill and version, plus the commit you tested;
- the environment: operating system, Python version, and the versions of any
  external programs involved;
- the exact commands to reproduce it, and what you observed versus expected;
- the impact you believe it has.

A proof of concept against a throwaway repository is welcome. Please do not test
against anyone else's data.

## What to expect

| Step | Target |
|---|---|
| Acknowledgement | within 7 days |
| First assessment | within 14 days |
| Fix or documented mitigation | depends on severity; you will be kept informed |
| Credit | offered in the advisory unless you prefer to stay anonymous |

If a report turns out to be a documented limit rather than a vulnerability, you
will get that answer with the reasoning and a link to where it is documented.

## Scope

**In scope**

- A skill doing something its manifest and documentation do not declare.
- A guard that can be bypassed without the user noticing — for example an audit
  reporting a clean result while an out-of-policy change sits on disk. Exactly
  this was found and fixed in Cordon (defect C11 in its test report).
- State handling that can be corrupted into an unsafe result.
- Code execution triggered by data a skill reads rather than by the user.
- Anything in `tools/` that could be abused through repository content.

**Out of scope**

- The documented limits of a skill. Cordon audits Git-visible changes; it is not
  an OS sandbox, and files excluded by `.gitignore` or writes through a symlink
  to a target outside the repository are outside its evidence model. Each skill's
  `TEST_REPORT.md` states its limits — check there first.
- A hostile process that already has full write access to the machine. No skill
  in this repository claims to contain that.
- What the wrapped AI agent decides to do inside the permissions you granted it.
- Vulnerabilities in third-party software a skill merely invokes; report those to
  their maintainers.

## For users of this repository

- Read a skill before running it. Skills are inspectable on purpose: `SKILL.md`
  says what it does, `skill.json` declares its permissions, and the source is
  small enough to read.
- No skill here needs a secret, a token or network access of its own. If one ever
  asks you for a credential, treat that as a report-worthy finding.
- Skills work inside your Git repository. Commit or stash your work before
  handing it to an agent, so a review is a diff rather than an archaeology
  project.
- Grant an agent the narrowest permission mode that still lets it work.

## Supported versions

The `main` branch is supported. Skills carry their own semantic version; fixes
land on `main` and are released as a new skill version rather than backported.
