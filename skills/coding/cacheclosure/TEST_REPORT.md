# Test report — CacheClosure 1.0.0

Date: 2026-08-15

## Result

Frozen protocol: **PASS**.

Local pre-promotion run:

```text
16 tests
0 failures
0 errors
core.py coverage: 95.7%
historical recovery: 2/3
known witness remaining on repaired counterparts: 0
protocol gate: PASS
```

GitHub Actions run `31850105648` then executed the same frozen protocol on:

- Ubuntu / Python 3.10 — PASS
- Ubuntu / Python 3.13 — PASS
- macOS / Python 3.10 — PASS
- macOS / Python 3.13 — PASS

## Reproduction

```bash
cd skills/coding/cacheclosure
PYTHONPATH=src python3 tests/run_tests.py --min 95
```

The test suite is offline and uses only the Python standard library. Historical
fixtures are minimized repository snapshots; the exact upstream commits are
recorded in `RESEARCH.md`.

## Historical oracles

| Repository | Broken | Repair | Result |
|---|---|---|---|
| KinesisCorporation/Adv360-Pro-ZMK | `962cb1d...` | `97f5d739...` | recovered; repair clears witness |
| LuvHakii/zuban-wasm-patches | `5bd20409...` | `193b3b7e...` | recovered; repair clears witness |
| kirpalricky/yapboard | `fd361701...` | `c955411c...` | deliberately not detected |

Frozen threshold: at least 2/3 recovered. Observed: 2/3.

## False-success controls

The suite requires the Kinesis broken snapshot to report its empty manifest glob
and the fixed snapshot to clear it. It requires the Zuban broken snapshot to
report both `patches/*.patch` and the cached `.patched` sentinel, while removing
the sentinel write, moving the sentinel outside the cache, deleting the alleged
input, or using the repaired key must suppress the finding. Yapboard remains a
negative control for a defect whose causal input lives in runtime build metadata.

## Asymmetry

500-iteration median on the minimized Zuban witness:

```text
full discovery:            0.688 ms
minimized witness verify:  0.054 ms
verify / find:             7.9%
```

Frozen death threshold: verification greater than 25% of discovery. Observed:
7.9%.

## Defects found while developing the detector

The first workflow field parser accepted `name:` but not the YAML sequence form
`- name:`. That lost the cache step's human name. A regression test now pins the
sequence-item form.

A test fixture also over-escaped `${{ ... }}` expressions, preventing symbolic
cache-path matching. The fixture was corrected. No threshold or historical
repository SHA changed after either defect.

## Limits

- The parser implements the workflow subset required for `actions/cache`,
  literal key/path fields and later `run` steps. It is not a general YAML parser.
- `hashFiles` arguments must be string literals for exact evaluation.
- Sentinel analysis recognizes shell `if [ ! -f marker ]; then ...; touch
  marker; fi` patterns plus repository-local inputs rooted at `$REPO` or
  `$GITHUB_WORKSPACE`.
- Runtime-generated cache identity inputs are outside v1.0.0. Yapboard is the
  frozen example.
- A clean scan is not proof that every cache identity is complete.
