# CacheClosure

Use CacheClosure when a repository uses `actions/cache` and a coding task can
change build inputs, generated state, patches, manifests or scripts without an
obvious cache miss.

## Procedure

1. Run `cacheclosure <repository> --json` from any directory.
2. Treat only emitted findings as proven by this skill. Do not infer additional
   cache defects from naming, style or intuition.
3. For `EMPTY_HASH_INPUT`, inspect `evidence.patterns`. The witness means the
   literal `hashFiles(...)` call resolved to zero files in the analysed tree.
4. For `SENTINEL_UNKEYED_INPUT`, inspect `sentinel`, `input_pattern`,
   `unkeyed_files` and `cache_paths`. The witness means a restored sentinel can
   skip a block that reads real repository files absent from the primary key's
   file closure.
5. Repair the workflow only if the repository's intended cache semantics are
   clear. The usual repair is to include the real causal input in the primary
   key, but CacheClosure does not choose or apply the patch.
6. Run CacheClosure again. The exact witness must disappear.
7. Run the repository's own build/tests. CacheClosure is not their substitute.

## Exit status

- `0`: no implemented rule proved a defect.
- `1`: at least one proven witness was emitted.
- other non-zero statuses: execution error; do not reinterpret them as a cache
  finding.

## Constraints

- No LLM is used as an oracle.
- No repository file is modified.
- No command from the analysed repository is executed.
- No network access is used.
- v1.0.0 is not a general YAML parser and does not claim complete stale-cache
  detection.
- A reported unkeyed input must resolve to an existing repository file; an
  arbitrary string in a shell script is not enough.

The frozen historical protocol and exact upstream commits are in
`FROZEN_PROTOCOL.md` and `RESEARCH.md`.
