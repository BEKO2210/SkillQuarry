# Emberfield

Create generative art with p5.js: an algorithmic philosophy first, then its
expression as seeded, reproducible code in an interactive viewer.

The method is inherited from Anthropic's `algorithmic-art` skill (Apache-2.0,
see NOTICE.md) and kept because it works: art made by naming an aesthetic idea
and then building the algorithm that embodies it is consistently better than
art made by accumulating effects.

## Use this skill when

- someone asks for generative art, algorithmic art, code art;
- flow fields, particle systems, growth simulations, noise landscapes;
- "make me something beautiful I can explore" — parameters included;
- a piece needs to be **reproducible**: the same seed must yield the same image.

## Do not use it for

- copying a named artist's style — original systems only;
- static images with no algorithm behind them (that is a different job);
- charts and data visualisation (the numbers dictate the form there).

## The two steps

### 1 · Write the algorithmic philosophy (a `.md` file)

Before any code: a short manifesto for a generative movement of your own
invention. Name it. Give it three to five principles that can be *computed* —
emergence, constraint, decay, accumulation, interference. One paragraph on what
the viewer should feel. This file is part of the deliverable.

The philosophy is not decoration. Every parameter the artwork later exposes
must trace back to one of its principles; if a slider cannot be justified by
the manifesto, the slider goes.

### 2 · Express it in code (one `.html` file)

Start from `templates/viewer.html`. It carries the frame — seed field,
Render, Prev/Next/Random seed, Reset, Save PNG, a parameters section — and a
demo algorithm marked `DEMO ALGORITHM — replace`. Replace the demo with the
philosophy's algorithm; leave the frame's element IDs alone, tools and tests
rely on them:

```text
#seed-input  #regenerate  #seed-prev  #seed-next  #seed-random
#save-png    #canvas-container
```

`templates/generator.js` collects the p5.js craft rules: parameters in one
object, classes for entities, `noLoop()` plus explicit `redraw()`, and how to
scale work so the sketch stays interactive.

## The seeding law

Everything random flows from the one seed in `#seed-input`:

```js
randomSeed(frame.seed());
noiseSeed(frame.seed());
```

Never call `random()` before the seeds are set, never use `Math.random()`
inside the algorithm, never fold `Date.now()` into the drawing. **The same seed
must render the same image, pixel for pixel** — that is what makes a piece
shareable ("look at seed 512144") and what the test suite verifies headlessly.
The one sanctioned use of `Math.random()` is the Random-seed button itself.

## Craft rules

- 60fps is not required; being alive is. Prefer `noLoop()` with `redraw()` on
  parameter change for dense still images; use `loop()` only when motion is
  the philosophy.
- Bound every loop by a parameter, not a constant — the sliders are the
  exploration, and exploration must not freeze the tab.
- Palette: three to five colours, exposed as colour inputs. Dark grounds show
  structure; the viewer's chrome is deliberately darker than any artwork
  should be.
- Alpha accumulation over thousands of strokes reads as depth; single opaque
  strokes read as clipart.
- Guard the edges: kill or wrap particles that leave the canvas, do not let
  them pile on the border.

## Deliverables

For a piece called `<name>`:

```text
<name>-philosophy.md    the movement: name, principles, intended feeling
<name>.html             the artwork: viewer frame + the algorithm, self-contained
```

The HTML needs the network once, for the pinned p5.js CDN script (SRI-hashed);
everything else is inline.

## Stop conditions

- The philosophy cannot be stated in computable principles — stop and sharpen
  it before writing code.
- The sketch takes longer than about two seconds to render at default
  parameters — reduce the default counts; the maximum slider position may be
  slow, the default must not be.
- Reproducibility breaks (same seed, different image) — that is a defect, not
  a feature; find the unseeded randomness and remove it.
