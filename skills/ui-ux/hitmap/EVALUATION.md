# HITMAP historical evaluation — verdict

Date: 2026-08-15 · Evaluator: independent run on the maintainer's machine
(Chromium oracle: Google Chrome 151, local HTTP allowed).

## Binding verdict

**FAIL — pass boundary 1 is not met. Under the frozen protocol the candidate
dies, and it must not be published by softening a threshold.**

## What was run

Pair 1 of the pinned oracle pairs, `runshu-W/nullpoint-descent` at the known-bad
SHA `6c631160`, built with its own toolchain (`vite build`) and served over
local HTTP. The other two pairs were not run: boundary 1 ("3/3 known-bad SHAs
produce the expected witness finding") had already failed, and failure of
boundaries 1–5 kills the candidate regardless of the remaining pairs.

## The defect is real — the protocol's oracle idea holds

An independent event probe (CDP `Input.dispatchMouseEvent`, the confirmation
step the protocol itself prescribes) reproduced the historical failure exactly:

```text
before click:  div.card visible (display:block), click handler on the canvas underneath
real click at canvas centre (390,247)
after click:   div.card still visible — the handler never ran, the game cannot start
receiver:      DIV (the card), not the canvas
```

This matches the human fix commit `5dc0df1a` word for word.

## The detector cannot see its own witness

```text
hitmap scan http://127.0.0.1:8111/  ->  verdict PASS, targets 0
```

Zero eligible targets. The page's only interactive surface is a `<canvas>` with
an `addEventListener('click', …)`, and the occluder is a plain `<div>`. Neither
matches the frozen eligibility gate (`button/input/select/textarea/a[href]`,
ARIA roles, `tabindex`). The detector's discovery is *semantic*; the witness the
protocol pinned is *listener-driven*. The very first oracle pair therefore lies
outside the instrument's field of view.

This is not an implementation bug. `core.py` classifies correctly, `cdp.py` is a
clean stdlib CDP client, and the 17 offline tests pass. The eligibility
definition itself — frozen in the protocol — excludes the witness.

## Secondary findings, for a possible v2

- Browser discovery prefers `chromium` over `google-chrome`; on this machine the
  snap-packaged chromium takes longer than the 10-second DevTools deadline, so
  the scan dies with `ORACLE_ERROR` unless `HITMAP_BROWSER` is set.
- `scan` exits 3 on findings and 0 on PASS; a PASS produced by *zero targets* is
  indistinguishable from a PASS over two hundred reachable ones. An empty
  surface should be its own outcome.

## What a v2 must change

Discovery has to see listener-bearing surfaces, not only semantically
interactive elements: `DOMDebugger.getEventListeners` over the document (or
`getEventListeners` via CDP on candidate nodes) adds exactly the class the
first oracle represents — canvas games, div-click UIs. That is a new protocol
version with re-frozen boundaries, evaluated from scratch. The remaining two
oracle pairs stay valid for it.

## Status

Research. Not promoted, not in the registry, not on the site.
