# Research evidence

Only primary sources are used here: upstream repositories, upstream commits,
and GitHub's own Actions documentation.

## GitHub semantics used by the detector

GitHub Actions documents `hashFiles(path)` as hashing the files matching the
workspace-relative pattern and returning an **empty string when the pattern
matches no files**:

- https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#hashfiles

`actions/cache` defines `key` as the explicit cache identity and `path` as the
files/directories restored and saved:

- https://github.com/actions/cache
- https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching

These semantics make `EMPTY_HASH_INPUT` mechanically decidable for literal
patterns.

## Historical oracle A — Kinesis Adv360 ZMK

Repository: https://github.com/KinesisCorporation/Adv360-Pro-ZMK

Broken commit:
`962cb1d30eb08e9927cf967eea3c1d3bb5d0d53d`

Repair:
`97f5d7394d36f60754a483bf5551e16d996fe406`

Repair message states that `hashFiles('manifest-dir/west.yml')` never matched a
file, making the key invariant to ZMK version changes. The patch changes both
cache keys to `hashFiles('config/west.yml')`.

Canonical repair:
https://github.com/KinesisCorporation/Adv360-Pro-ZMK/commit/97f5d7394d36f60754a483bf5551e16d996fe406

## Historical oracle B — zuban-wasm-patches

Repository: https://github.com/LuvHakii/zuban-wasm-patches

Broken commit:
`5bd204092146256b2d89c61781ebe22ef1b0abf8`

Repair:
`193b3b7e8f26e55c02fad17876ab2967382ad484`

At the broken commit:

- the cache stores `$ROOT/zuban`;
- `scripts/build.sh` changes directory to `$SRC == $ROOT/zuban`;
- if `.patched` exists it skips `git apply $REPO/patches/*.patch`;
- `.patched` is created after the apply;
- the primary key hashes `scripts/setup.sh` but not `patches/*.patch`.

The repair adds `patches/*.patch` to the key and explicitly states that the
cached `.patched` marker caused CI to restore an already-patched tree and skip
recompilation after patch changes.

Canonical repair:
https://github.com/LuvHakii/zuban-wasm-patches/commit/193b3b7e8f26e55c02fad17876ab2967382ad484

## Historical oracle C — Yapboard

Repository: https://github.com/kirpalricky/yapboard

Broken commit:
`fd3617018af64f9dd48a383c463b6e7301ec8cd5`

Repair:
`c955411c362f89e1098c8ec5bf556ff1b59daca8`

The repair states that SwiftPM's cached `.build` directory contained absolute
checkout paths. After a repository rename the cache key still matched because it
only included `Package.resolved`; the repair adds
`${{ github.event.repository.name }}` to the key.

Canonical repair:
https://github.com/kirpalricky/yapboard/commit/c955411c362f89e1098c8ec5bf556ff1b59daca8

Current v0 deliberately does **not** detect this case. Runtime build metadata is
outside the repository-file closure v0 can prove.
