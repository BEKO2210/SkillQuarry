# Emberfield test report

Date: 2026-08-15 · Version 1.0.0 · Branch `feat/emberfield-skill`

## Summary

```text
contract          7 tests   PASS
provenance        4 tests   PASS
template syntax   1 test    PASS
rendering         2 tests   PASS   (headless Chromium, pixel hashes)
---------------------------------
total            14 tests   PASS   in 13.0 s, 0 skipped
```

Toolchain: Python 3.12.3 · Google Chrome 151 (headless) · node 22 ·
p5.js 1.7.0 pinned by SHA-256 `bb7f8f14…` and SRI `sha384-Mhzoc5…`.

## Contract — 7 tests

The viewer template promises a frame that tools and future artworks rely on.

- every promised control exists: `#seed-input`, `#regenerate`, `#seed-prev`,
  `#seed-next`, `#seed-random`, `#save-png`, `#canvas-container`;
- the seeding law is modelled in the template itself
  (`randomSeed(frame.seed())`, `noiseSeed(frame.seed())`);
- `Math.random` appears exactly once — on the Random-seed button, the one
  sanctioned use;
- no clock (`Date.now`, `performance.now`, `new Date`) flows into the drawing;
- the p5.js CDN reference is pinned with subresource integrity;
- the viewer carries no upstream branding — the Apache licence covers code,
  not trademarks, and this test keeps the port honest;
- apart from the pinned p5.js, the artwork references no external resource.

## Provenance — 4 tests

The right to publish this skill rests on files that must not quietly change:
the unaltered Apache-2.0 text, a NOTICE that names the origin and lists the
changes, the upstream best-practices template with its guidance intact, and a
SKILL.md that still teaches the two-step method.

## Rendering — 2 tests

The skill's central promise, held by a real browser rather than by review:

```text
seed 12345, rendered twice   ->  SHA-256 identical
seed 512144, rendered once   ->  SHA-256 different
```

The second test guards the first against lying: if rendering silently failed,
two empty canvases would agree and "deterministic" would mean "broken". The
pages under test load the exact bytes the CDN serves — fetched once, verified
against the SHA-256 pin, then used from disk, so the suite neither depends on
the CDN being up nor drifts from what users receive.

## Honest notes

- The determinism claim is **same machine, same browser build** — it is what
  makes a seed shareable in practice. Cross-platform pixel identity is not
  claimed; antialiasing differs between font and GPU stacks.
- CI runs with `EMBERFIELD_REQUIRE=1`, so an environment that quietly loses
  Chrome or the network fails instead of skipping.
- One correction during development: the p5.js SHA-256 pin was first written
  from memory and wrong; the tests refused to run against the real file, which
  is exactly what the pin is for. It now records the measured hash.
