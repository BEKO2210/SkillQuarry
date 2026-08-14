# Test Report — Example Skill 1.0.0

Date: 2026-08-14

| | |
|---|---|
| Python | 3.12.3 |
| Platform | Linux 6.8 (x86_64) |
| Automated tests | **16 passed, 0 failed** |
| Line coverage of `core.py` | **100%** (51/51) |
| Dependencies | none |

Reproduce:

```bash
cd templates/example-skill
python3 tests/run_tests.py --min 100
```

## What is covered

| Area | Cases |
|---|---|
| Counting | multi-line file, file without a trailing newline, empty file |
| Refusal | missing path, directory instead of file, oversized file (limit named in the message), non-UTF-8 bytes |
| Ordering | inputs are sorted, so output is reproducible |
| Totals | per-file numbers add up to the totals block |
| Atomic write | replace on rewrite, no temp file left behind, no temp file after a failed `os.replace` |
| CLI | stdout report, `--out` file, unreadable input exits 2 with the cause on stderr, `--version` exits 0 |

The installer and uninstaller were exercised manually into a temporary prefix:
`install.sh` self-checks by running `example-skill --version`, and `uninstall.sh`
removes exactly the launcher and the module directory it created.

## Defects found while writing it

**E1 — the `--version` test leaked argparse output into the test run.**
`argparse` writes the version straight to the process stdout, so the suite printed
`example-skill 1.0.0` between test results. Fixed by redirecting stdout inside the
test. Harmless in itself, but a test report that prints stray output trains a
reviewer to ignore output.

## Known limits

- Only Linux and Python 3.12 were exercised locally; CI runs the same suite on
  every supported version.
- Files are read fully into memory, bounded by `DEFAULT_MAX_BYTES` (5 MiB). A
  streaming implementation would be the first change if the limit ever mattered.
- Word counting uses `str.split()`, which is whitespace-based; it does not do
  linguistic word segmentation.
