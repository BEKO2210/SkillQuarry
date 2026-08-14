---
name: example-skill
description: Summarise UTF-8 text files as JSON — line, word and byte counts with totals. This is also the reference template for building a SkillQuarry skill, so use it when someone asks how a skill is structured, what its manifest must contain, or how its tests are expected to look.
---

# Example Skill

Counts lines, words and bytes across one or more UTF-8 text files and reports the
result as JSON. It exists to be copied: every part of it is the smallest honest
version of what the [skill specification](../../docs/SKILL-SPEC.md) requires.

## Use it

```bash
example-skill README.md src/*.py
example-skill README.md --out report.json
```

Exit codes: `0` success, `2` a file could not be read.

## Rules it demonstrates

- **Refuse, do not guess.** A missing file, a directory, an oversized file or
  non-UTF-8 bytes raise an error naming the cause. A zero count would be
  indistinguishable from an empty file.
- **Write atomically.** `--out` writes through a temp file, `fsync` and
  `os.replace`, so a reader never sees half a report.
- **No dependencies.** Standard library only, offline, no install-time downloads.
- **Deterministic output.** Files are sorted, so two runs on the same input match.

## Build your own from it

```bash
python3 tools/new_skill.py --name my-skill --display "My Skill" --category testing
```

That copies this template, renames the module and the CLI, and leaves you with a
skill that already passes `tools/validate_skills.py` and its own coverage gate.
Replace `src/<module>/core.py` with your logic and rewrite the tests around it —
keep the shape, the refusal behaviour and the gate.
