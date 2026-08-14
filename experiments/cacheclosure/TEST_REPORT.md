# Test report — CacheClosure experiment v0.1.0

Date: 2026-08-15

## Environment

Local pre-commit run:

- Linux container environment
- Python 3 standard library only
- no network access during the test suite
- historical evidence fixtures are minimized and embedded in
  `tests/test_cacheclosure.py`

## Reproduction

```bash
cd experiments/cacheclosure
PYTHONPATH=. python3 tests/run_tests.py --min 95
```

Observed before repository commit:

```text
16 tests
0 failures
0 errors
core.py coverage: 95.7%
historical recovery: 2/3
known witness remaining on repaired counterparts: 0
protocol gate: PASS
```

The coverage calculation uses Python's standard-library `trace` executable-line
map. Import/class-definition lines loaded before tracing are included in the
denominator, so the reported 95.7% is conservative for callable detector logic.
The experiment gate is fixed at 95%.

## Frozen historical results

| Repository | Broken | Repair | v0 result |
|---|---|---|---|
| KinesisCorporation/Adv360-Pro-ZMK | `962cb1d...` | `97f5d739...` | recovered; repair clears witness |
| LuvHakii/zuban-wasm-patches | `5bd20409...` | `193b3b7e...` | recovered; repair clears witness |
| kirpalricky/yapboard | `fd361701...` | `c955411c...` | not detected |

Required threshold: >=2/3. Observed: **2/3**.

## Defect found while building the detector

The first parser version found the cache step but lost its human step name. The
field parser accepted `name:` but not YAML's `- name:` form. A test failed with
`actions/cache != cache source + cargo`. The parser now accepts the sequence-item
prefix and the regression is pinned by
`test_parse_cache_step_block_path_and_name`.

A second test-fixture defect over-escaped `${{ ... }}` expressions as
`${{{{ ... }}}}`. That prevented symbolic cache-path matching and made the
Zuban historical oracle disappear. The fixture was corrected; this was test
construction error, not detector behavior.

## False-success controls

The suite requires all of the following:

- Kinesis broken reports the exact empty glob.
- Kinesis repair reports no known witness.
- Zuban broken reports `patches/*.patch` and the cached `.patched` sentinel.
- Zuban repair reports no known witness.
- removing the sentinel `touch` suppresses the Zuban finding.
- moving the sentinel outside the cached path suppresses the finding.
- deleting the alleged repository input suppresses the finding rather than
  inventing a dependency.
- the Yapboard case remains a documented miss.

## Asymmetry measurement

500-iteration median on the minimized Zuban fixture:

```text
full discovery:             0.688 ms
minimized witness verify:   0.054 ms
verify / find:              7.9%
```

Frozen death threshold: verification >25% of discovery. Observed: 7.9%.

## Limits

- v0 parses the subset of GitHub Actions YAML needed to locate `actions/cache`,
  literal `key`, multiline `path`, and later `run` steps. It is not a general
  YAML parser.
- `hashFiles` arguments must be string literals for exact local evaluation.
- sentinel analysis currently recognizes shell `if [ ! -f marker ]; then ...;
  touch marker; fi` patterns and repository-local inputs rooted through
  `$REPO` or `$GITHUB_WORKSPACE`.
- runtime-generated cache identity inputs are outside v0; Yapboard is the frozen
  example.
- local testing here is Linux only. The branch CI is required to pass on both
  Ubuntu and macOS before promotion.
