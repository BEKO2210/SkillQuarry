# HITMAP

Find browser controls that are visible and enabled but have no pointer-reachable
sampled interior point because another rendered element wins the hit test.

## Use this skill when

- a UI control looks correct but clicks do nothing;
- overlays, banners, drawers, portals, sticky headers or z-index changes were edited;
- E2E tests are green but users report that a visible control cannot be clicked;
- a coding agent changed CSS/layout and needs a mechanical post-change interaction
  check rather than a screenshot judgement;
- you need to prove that an apparent interaction failure exists in browser runtime,
  not merely in source reasoning.

## Do not use this skill for

- general UX scoring;
- accessibility/WCAG compliance;
- visual-regression testing;
- keyboard-only defects;
- touch-specific event-sequence defects;
- deciding whether a UI is attractive, readable or well designed;
- claiming that a clean scan proves the interface works.

## Phase 0 — Establish the oracle

Run:

```bash
hitmap doctor
```

If it returns `ORACLE_UNAVAILABLE`, stop. Do not replace the browser oracle with
source inspection, an LLM judgement, jsdom or a screenshot.

Pin the viewport used by the application or bug report. Default is 1280×720.

## Phase 1 — Reach the real state

Start the application's real development or production server yourself. Do not
invent a route. Prefer the user-facing entry path over demo/test modes that bypass
first-run overlays or gates.

Record:

```text
URL
viewport
how the state was reached
pre-existing failing tests
```

HITMAP 0.1 scans one state per invocation. If the bug needs a modal/menu/second
route, reach that state deterministically and scan it separately.

## Phase 2 — Scan

```bash
hitmap scan <URL> --width 1280 --height 720 --json > hitmap.json
```

A geometry finding requires all of these:

```text
eligible target          true
sample points            exactly 9
reachable sampled points exactly 0
```

Eligibility excludes disabled/hidden/inert/off-viewport/tiny targets. A point is
reachable only when the browser hit-test receiver is the target, a descendant, or
its associated label.

Do not promote a target with 1–8 reachable points to the same finding class. That
would change the frozen decision rule.

## Phase 3 — Inspect the witness, not the appearance

For each finding report:

```text
finding id
target selector
9 sampled coordinates
receiver(s) that won the hit test
viewport
URL
```

Then inspect the smallest relevant DOM/CSS relation: the target, the receiver and
their positioning/stacking/pointer-event rules. Do not perform a broad restyle.

Common repair classes include:

- decorative overlay should use `pointer-events: none`;
- interactive child needs explicit pointer events while its decorative parent does
  not;
- stale full-screen layer should be removed/hidden after transition;
- event handler is attached below an overlay that necessarily receives the click.

These are examples, not automatic fixes. The browser evidence determines the
problem; application semantics determine the repair.

## Phase 4 — Verify the smallest repair

Run the application's existing tests first, then rerun HITMAP at the exact same
URL/state/viewport.

A historical-oracle style result is:

```text
before: target reported with 0/9 reachable points
repair: minimal code/CSS change
existing tests: no new regression
after: same target no longer reported
```

Do not call that universal UX correctness. Call it only a repaired hit-test
reachability failure.

## Prototype limits that must stay visible

HITMAP 0.1.0 does not yet traverse iframes or shadow roots, discover arbitrary
JavaScript-only click listeners, explore state graphs automatically, or dispatch a
second independent real click confirmation. Therefore its finding confidence is
`geometry`, not `confirmed-event`.

The candidate must not be promoted beyond experimental until the frozen historical
protocol in `FROZEN_PROTOCOL.md` passes without changing its thresholds.
