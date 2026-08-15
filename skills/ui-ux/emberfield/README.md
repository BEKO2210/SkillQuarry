# Emberfield

**Generative art with p5.js — a philosophy first, then seeded, reproducible
code.**

```bash
cd skills/ui-ux/emberfield && ./install.sh
```

Then, in Claude Code: *"Create generative art of slow rivers of light."* The
skill answers with two files — a written algorithmic philosophy and a
self-contained `.html` artwork with seed navigation, parameter sliders, colour
pickers and PNG export. `examples/emberflow.html` is a worked piece.

## Why a philosophy first

Art made by accumulating effects converges on the same soup everyone else's
effects converge on. Art made by naming an aesthetic idea — three to five
principles that can be *computed* — and then building the algorithm that
embodies them stays distinct, and every slider has a reason to exist. That
method is inherited from Anthropic's `algorithmic-art` skill and kept intact.

## The seeding law

```js
randomSeed(frame.seed());
noiseSeed(frame.seed());
```

Everything random flows from the one visible seed. The same seed renders the
same image, pixel for pixel — which turns a piece into something shareable
("look at seed 512144") and turns taste into a testable promise:

```text
render seed 12345, twice, headless Chromium  ->  identical SHA-256
render seed 512144 once                      ->  different SHA-256
```

That is the heart of the test suite. A creative skill does not get to skip
having one.

## Provenance, stated plainly

Emberfield is a derivative of
[anthropics/skills](https://github.com/anthropics/skills) `algorithmic-art`,
used under **Apache-2.0**. The licence ships unchanged in `LICENSE.txt`; the
changes — new viewer without upstream branding, our visual language, tests,
installer, manifest — are listed in [NOTICE.md](NOTICE.md). No endorsement by
or affiliation with Anthropic is claimed. A test fails if upstream branding
ever appears in the viewer.

## Threat model

- **The skill runs nothing.** It is a document plus templates; the agent
  writes files where it is asked to.
- **Generated artworks touch the network once**: the pinned p5.js CDN script,
  locked with subresource integrity (`sha384-…`), so a compromised CDN serves
  nothing the browser will execute. Everything else is inline.
- **The tests fetch p5.js once** and refuse to run it unless its SHA-256
  matches the pin.
- `install.sh` copies files into `~/.claude/skills/emberfield` and nowhere
  else; `uninstall.sh` refuses to delete a directory it cannot identify as its
  own installation.

## Requirements

| | |
|---|---|
| Runtime | none — a browser opens the artwork |
| Tests | Python 3.10+, a Chromium-family browser, `node` for template syntax |
| Platforms | Linux, macOS |

## Tests

```bash
python3 tests/run_tests.py                      # skips what the machine lacks
EMBERFIELD_REQUIRE=1 python3 tests/run_tests.py # CI: a skip is a failure
```

14 tests; the numbers and what they hold down are in
[TEST_REPORT.md](TEST_REPORT.md).
