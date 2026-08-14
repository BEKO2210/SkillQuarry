# Where LockScope comes from

This skill was promoted from an experiment that was run twice, failed once, and
was only released after the second attempt passed a protocol frozen before the
first substantive run.

## The first attempt failed, and why that mattered

Version 1 discovered lock acquisitions with regular expressions. It handled the
common shape and missed this one:

```rust
let mut guard = state
    // a comment where a pattern gives up
    .lock()
    .await;
```

That is valid, ordinary Rust. The lesson was not "improve the pattern" — Rust is
not a regular language, and the next miss would have been a different shape. The
candidate layer was replaced with a Rust syntax tree, and everything above it —
semantic resolution, macro expansion, lock-order analysis, compiler probes,
repair verification — was kept.

The production engine in `src/lockscope/syntax.py` is that structured layer. The
v1 acquisition scanner is not part of this skill in any form.

## The frozen evaluation

| | |
|---|---|
| Research branch | `test/lockscope-v2-20260814` |
| Protocol frozen at | `65e58908f3c0bd5e7475ac5e4696e3d77b11bb62` |
| CI amendment | `4353f0bfedf12018c28517c47090455d6327a602` |
| Final report | `78d99dd2a0427588bac664c76326effbfff5db49` |
| Passing workflow run | `31823072283` |
| Verdict | `PASS_V2` |

The branch is kept as evidence. Its full report is
`experiments/lockscope/V2_TEST_REPORT.md` on that branch.

What the evaluation established, on Ubuntu **and** macOS:

- 20 of 20 inherited semantic cases;
- 5 of 5 structured-syntax cases, including the shape that ended v1;
- 4 of 4 compiler `Send` probes;
- the expected lock-order cycles, and no false cycle in the control;
- a macro-generated Tokio acquisition detected through expansion;
- deterministic analysis;
- a Tokio contention repair that turns a deadlock into a completing program;
- three real repositories: Javis and Ferryman as historical oracles, mini-redis
  as a healthy baseline with an injected fault;
- 168.267 s for the real-repository stage, against a 720 s budget frozen in
  advance.

One amendment was made after the first workflow run, and it changed no
expectation: macOS system Python refused a global `pip install` under PEP 668
before any test executed, so the pinned packages moved into a virtual
environment. That constraint is now part of `install.sh`.

## What promotion changed

The experiment was not copied. It was rebuilt as a skill, and four things
changed in the process — each of them found by a test written for production,
not inherited from the research:

1. **The repair became structural.** The research repair matched lines with a
   regular expression, which contradicted the reason v2 existed. It now finds
   the acquisition and the await in the syntax tree, and refuses on branching
   control flow, on a use of the guard, and on anything that would move a
   binding out of its scope.
2. **Lock identity became path-relative.** The fallback identity of a lock
   contained an absolute path, so the same code analysed in two directories
   produced two different reports. A determinism test caught it.
3. **The analyser waits for the workspace.** rust-analyzer answers immediately
   while it is still loading — with nothing. The first three fixture cases were
   silently classified as "not a lock". The engine now waits for the workspace
   to load and never caches an empty answer.
4. **The method's own definition became the primary evidence.** For a receiver
   like `Arc::clone(&state)`, the receiver only ever resolves to `Arc`. Asking
   where the called `lock_owned` is *defined* answers the question directly.

## What is claimed, and what is not

`PASS_V2` means the implementation passed that specific frozen evaluation, and
the production suite reproduces it. It is **not** a claim of complete Rust
coverage, and **not** a claim that every concurrency bug is detectable. The
limits are listed at the end of [SKILL.md](SKILL.md) — unbound temporary guards,
guards moved to another owner, procedural macros rust-analyzer cannot expand,
runtime contention, and Windows.
