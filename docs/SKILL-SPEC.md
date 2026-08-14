# SkillQuarry Skill Specification

Version 1.0 · normative for everything under `skills/`

A SkillQuarry skill is an **executable capability**, not a document. This
specification exists so a reviewer can judge one without reverse-engineering it,
and so tooling can read every skill the same way.

The machine-readable companion is [`registry/schema.json`](../registry/schema.json).
Where this document and the schema disagree, the schema decides — it is what CI
enforces through `tools/validate_skills.py`.

The words **must**, **should** and **may** carry their usual weight: *must* is
enforced by CI, *should* is expected of anything above `experimental`, *may* is
free choice.

---

## 1. Location and layout

A skill lives at `skills/<category>/<name>/`, where `<category>` is one of the
categories in the schema and `<name>` is the registry identifier.

```text
skills/<category>/<name>/
├── skill.json        must   manifest; the single source of truth for metadata
├── SKILL.md          must   instructions for the agent
├── README.md         must   documentation for a human
├── TEST_REPORT.md    should evidence: environment, results, defects, limits
├── install.sh        should dependency-free installer
├── uninstall.sh      should removes exactly what the installer created
├── src/              should implementation
├── tests/            should automated tests, runnable offline
└── RESEARCH.md       may    the sources behind the design
```

Anything the manifest points at must exist. CI checks this.

The reference implementation of this layout is
[`templates/example-skill`](../templates/example-skill) — a small working skill
with its own tests and coverage gate. `python3 tools/new_skill.py` copies it into
place with the module, CLI and manifest renamed. The template lives outside
`skills/`, so it never appears in the registry, but its manifest is validated and
its suite runs in CI.

## 2. The manifest

`skill.json` must validate against the schema. Required fields:

| Field | Meaning |
|---|---|
| `name` | Registry identifier, lowercase kebab-case, **equal to the directory name** |
| `displayName` | Human-facing name |
| `version` | Semantic version of the skill, independent of the repository |
| `description` | One paragraph of plain sentences — no marketing, no claims a reviewer cannot check |
| `category` | **Equal to the parent directory** |
| `license` | SPDX identifier, compatible with the repository's Apache-2.0 |

Recommended fields, all validated when present: `tagline`, `banner`,
`highlights`, `quickstart`, `agents`, `compatibility`, `platforms`, `requires`,
`permissions`, `state`, `tests`, `quality`, `keywords`, `entrypoints`, `icon`,
`homepage`, `research`, `workflow`.

Unknown top-level fields are rejected. Metadata the schema does not cover yet
belongs under `extensions`, so a future schema version can adopt it deliberately.

### 2.1 The manifest drives the README

The skill list, the skill cards, the badge counters and `registry/skills.json`
are generated from the manifests by `tools/render_readme.py`. Never hand-edit
anything between the `SKILLS:*` markers in the root README — edit the manifest.

## 3. Declaring what the skill touches

Any skill that runs commands must declare `permissions` in plain language:

```json
"permissions": {
  "filesystem": "reads Git-visible repository state; writes only .cordon state",
  "shell": "spawns git, configured verifier commands, and optionally claude",
  "network": "none directly; only through the wrapped agent",
  "environment": "reads CORDON_PREFIX during install"
}
```

Skills that keep state inside a user's repository must declare `state` and must
hide that state through `.git/info/exclude`. **A skill must never modify a user's
`.gitignore`** — that file belongs to the user, and a rewritten `.gitignore`
outlives the run.

Security-relevant behaviour is never implicit. If a skill can delete files, push
commits, install software, or send data anywhere, the manifest and `SKILL.md`
must say so.

## 4. Dependencies

A skill must run with what a developer machine already has: a shell, `git`, and
Python 3.10+ where Python is used. Third-party runtime packages are not accepted;
`requires.packages` exists to declare unavoidable exceptions and must stay empty
in practice. Installers must not download anything.

The reason is inspectability: a reviewer can read every line a skill will
execute, and a user in an offline or locked-down environment can still run it.

## 5. Testing

Automated tests are what separates a skill from a prompt.

- Tests must run offline, from the skill directory, with one command, and that
  command must be named in `tests.command`.
- External programs must be simulated by a fake binary that honours the **same
  command-line contract** as the real one. Everything else — filesystem, git,
  subprocesses, locks — should stay real.
- The suite should cover five levels: the simple path; realistic multi-step use;
  an interruption and its recovery; a false success claim overruled by
  independent verification; and adversarial input, corrupt state and runaway loops.
- Coverage should be measured, reported and enforced by a threshold. Both current
  skills use the standard library's `trace` module and gate at 100% of the core
  module, excluding platform branches marked `# pragma: no cover`.
- Worst cases must be **calculated**, not hoped for. Random fuzzing that never
  reaches the arithmetic worst case has already hidden a real defect in this
  repository once.

Each skill ships a CI workflow at `.github/workflows/<name>-tests.yml` — or names
another file in `workflow` — that runs the suite on every supported Python
version and platform.

## 6. Evidence

`TEST_REPORT.md` should record:

1. the environment actually used, with versions;
2. results with the exact reproduction command;
3. **defects found, with cause, fix and regression test** — including the
   author's own. A report without a single defect reads as a report that never
   looked;
4. known limits: what was not tested, what could break, what a reviewer must
   still check on their own machine.

Claims without a reproducible command do not belong in a test report.

## 7. Quality levels

| Level | Meaning |
|---|---|
| `experimental` | Early-stage; structure may still change |
| `verified` | Manifest and structure validate; documentation is complete |
| `tested` | Automated tests exist, run in CI, and their report is honest about limits |
| `trusted` | Reproducible testing plus a security review by someone other than the author |
| `certified` | Highest level; reserved, not yet awarded |

Authors may claim up to `tested` and must be able to prove it. `trusted` and
above are set by the repository owner, never self-declared.

## 7.1 Security metadata

Any skill whose `permissions.shell` is not `none` must carry a machine-readable
`security` block, and CI rejects it otherwise:

```json
"security": {
  "network_access": "none | indirect | direct",
  "runs_external_commands": true,
  "writes_outside_repository": false,
  "requires_secrets": false,
  "destructive_operations": ["rewrites source files in place"],
  "threat_model": "TEST_REPORT.md",
  "reviewed_by": "who reviewed it independently of the author, and when"
}
```

The block must agree with the prose in `permissions` — a skill that describes
spawning commands and then declares `runs_external_commands: false` is rejected.
`destructive_operations` lists irreversible actions in plain language; an empty
list means none. `threat_model` points at the file stating what the skill does
**not** protect against.

## 7.2 Checksums

`registry/skills.json` records a `checksum` per skill: SHA-256 over every file a
user would install, including its repository-relative path and executable bit, and
excluding build output and caches. A changed byte, a rename or a lost `chmod +x`
changes it.

```bash
python3 tools/registry.py verify   # recompute and compare
```

CI runs that check, so a registry entry can never describe files that are no
longer there.

## 8. Versioning

Skill versions follow semantic versioning and move independently of the
repository:

- **major** — the CLI, the state format or the manifest contract changes in a way
  that breaks an existing user;
- **minor** — new capability, backwards compatible;
- **patch** — fixes and documentation.

Persisted state must carry a schema version and must refuse to load state written
by an incompatible version, rather than guessing.

A skill must state one version, not several: where a skill also declares a version
in `pyproject.toml` or in its module (`__version__`), CI checks that all of them
match the manifest.

## 9. Naming and user-facing text

- `name` is lowercase kebab-case, stable for the life of the skill; renaming is a
  new skill.
- User-facing text says what happened and what to do next. No exclamation marks,
  no praise of the tool, no invented certainty.
- An error message must name the cause and the remedy, in that order.

## 10. Checklist before opening a pull request

- [ ] `python3 tools/validate_skills.py` passes.
- [ ] `python3 tools/registry.py verify` passes.
- [ ] `python3 tools/render_readme.py --check` passes.
- [ ] The skill's own test command passes at its coverage gate.
- [ ] `TEST_REPORT.md` names environment, evidence, defects and limits.
- [ ] `permissions` and `state` describe what the skill really does.
- [ ] No third-party runtime dependency, no network access during install.
- [ ] A CI workflow exists for the skill.
