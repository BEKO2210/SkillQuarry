# CacheClosure experiment

CacheClosure is an experimental detector for GitHub Actions cache keys whose
identity is mechanically disconnected from cached state.

This directory is intentionally **not** a SkillQuarry skill yet. It must pass the
frozen historical protocol in `FROZEN_PROTOCOL.md` before promotion into
`skills/coding/` or the registry.

## Current mechanical rules

`EMPTY_HASH_INPUT`
: A literal `hashFiles(...)` call in an `actions/cache` primary key resolves to
  zero repository files. GitHub documents that such a call evaluates to the
  empty string, so that contribution cannot vary when repository files change.

`SENTINEL_UNKEYED_INPUT`
: A shell step executes under a cached directory, checks a file sentinel,
  creates that same sentinel after reading repository-local inputs, and those
  input files are absent from the primary key's `hashFiles` closure. Restoring
  the sentinel can therefore suppress the input-dependent work while the key
  stays unchanged.

Neither rule asks a model to judge correctness. Both produce a small witness
that can be checked from files, cache configuration, and shell control flow.

## Run

```bash
cd experiments/cacheclosure
PYTHONPATH=. python3 -m cacheclosure /path/to/repository
PYTHONPATH=. python3 -m cacheclosure /path/to/repository --json
```

Exit status is `1` when a proven witness is found, `0` otherwise.

## Test

```bash
PYTHONPATH=. python3 tests/run_tests.py --min 95
```

The offline suite includes minimized snapshots of three historical repositories.
The snapshots retain only the lines required by the oracle and name the exact
upstream commits in `RESEARCH.md`.

## Current verdict

The experiment recovers 2 of 3 frozen historical defects and reports zero known
witnesses on their repaired counterparts. The third historical case is an
intentional miss: SwiftPM cached absolute checkout paths, a fact not inferable
from the current mechanical rules without a runtime artifact inspection step.
