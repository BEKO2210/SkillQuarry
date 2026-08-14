# CacheClosure

CacheClosure detects a narrow class of GitHub Actions cache defects where the
cache identity is mechanically disconnected from state that can change the
cached result.

It does not score YAML style and it does not ask a language model whether a key
looks complete. A finding must carry a small witness that can be checked from
repository files and the workflow itself.

## Findings

### `EMPTY_HASH_INPUT`

A literal `hashFiles(...)` expression in an `actions/cache` primary key resolves
to zero files. GitHub documents that this contributes an empty string to the key,
so the contribution cannot change when repository files change.

### `SENTINEL_UNKEYED_INPUT`

A later shell step executes inside a cached directory and skips work when a
sentinel exists. The gated work reads repository-local files, the block creates
the same sentinel, and those files are absent from the primary key's
`hashFiles` closure. Restoring the sentinel can therefore suppress work that a
changed repository input should have triggered.

## Install

```bash
cd skills/coding/cacheclosure
./install.sh
```

Set `CACHECLOSURE_PREFIX` to install somewhere other than `~/.local`.

## Use

```bash
cacheclosure .
cacheclosure . --json
```

Exit status is `1` when one or more proven witnesses are found and `0` when none
of the implemented rules prove a defect.

## Evidence boundary

A zero exit status does not prove that a cache is sound. v1.0.0 only proves the
two patterns above. Runtime-only cache identity inputs are outside its closure;
the frozen Yapboard case in `FROZEN_PROTOCOL.md` is a deliberate miss.

## Verification

```bash
PYTHONPATH=src python3 tests/run_tests.py --min 95
```

The frozen protocol recovered 2 of 3 pinned historical defects, cleared the
known witness on both repaired counterparts, and passed GitHub Actions on Ubuntu
and macOS with Python 3.10 and 3.13 in workflow run `31850105648`.
