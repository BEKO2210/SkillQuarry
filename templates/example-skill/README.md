# Example Skill

The reference skill. Everything a SkillQuarry contribution must have is here in
its smallest honest form: a manifest, an agent-facing `SKILL.md`, a human-facing
README, a dependency-free installer with a matching uninstaller, real logic, real
tests and a coverage gate.

It is a working tool, not a stub — it summarises UTF-8 text files as JSON.

## Scaffold your own from it

```bash
python3 tools/new_skill.py --name my-skill --display "My Skill" --category testing
```

The result already validates and passes its gate:

```bash
cd skills/testing/my-skill
python3 tests/run_tests.py --min 100
```

Then replace `src/<module>/core.py` with your logic, rewrite the tests around it,
and update the manifest. Keep the shape.

## Use it directly

```bash
cd templates/example-skill && ./install.sh
example-skill README.md src/example_skill/core.py
example-skill README.md --out report.json
```

```json
{
  "totals": { "files": 2, "lines": 118, "words": 402, "bytes": 3990 },
  "files": [ { "path": "core.py", "lines": 84, "words": 271, "bytes": 2712 } ]
}
```

Exit codes: `0` success · `2` a file could not be read.

## What it demonstrates

| Rule | Where to see it |
|---|---|
| Refuse instead of guessing | `summarise_file` raises on a missing file, a directory, an oversized file and non-UTF-8 bytes |
| Atomic writes | `atomic_write_text`: temp file → `fsync` → `os.replace`, no temp left behind on failure |
| No dependencies | standard library only; the installer copies files and writes a launcher |
| Symmetric install/uninstall | `uninstall.sh` removes exactly what `install.sh` created |
| Deterministic output | inputs are sorted before rendering |
| A measured gate | `tests/run_tests.py --min 100` fails below 100% line coverage of `core.py` |

## Tests

```bash
python3 tests/run_tests.py --min 100
```

16 tests, 100% of `core.py`. Details and known limits: [TEST_REPORT.md](TEST_REPORT.md).

## Not in the marketplace

This template lives under `templates/`, not `skills/`, so it never appears in the
skill table or `registry/skills.json` — the registry stays a list of real
capabilities. Its manifest is still validated against the schema, and its tests
run in CI, so the example cannot rot.
