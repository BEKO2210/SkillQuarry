# HITMAP research record

Date: 2026-08-15

Question: can a UX skill discover a class of real interaction failures that humans
and authored tests systematically miss, while letting the browser decide whether a
finding is real?

## Candidate mechanism

The signal is the rendered hit-test relation, not source code:

```text
visible interactive target × interior coordinate -> top pointer receiver
```

Humans can inspect one control. They do not retain this relation for tens or
hundreds of controls across UI states. Finding therefore scales with the rendered
surface; verification of one candidate is cheap because the same point can be
requeried or clicked in seconds.

## Historical evidence

### 1. runshu-W/nullpoint-descent

Human fix:

- repository: `runshu-W/nullpoint-descent`
- known-bad parent: `6c631160971cc97ac74d24aa133b7eb003116a76`
- fix: `5dc0df1a1ad6ba3f3062d87bc2529953124bb471`
- commit message: `Fix: clicking the title card did nothing, so the game could not be started`

The fix states that the overlay covered the viewport above the canvas and the
handler that hid it was attached to the canvas underneath, so the first human
click could never reach the handler. The same commit records that **113 tests and
seven headless walkthroughs** missed the defect because they all used `?demo=1`,
which hid the card programmatically.

Fix URL:
`https://github.com/runshu-W/nullpoint-descent/commit/5dc0df1a1ad6ba3f3062d87bc2529953124bb471`

### 2. storybookjs/storybook

Human fix:

- repository: `storybookjs/storybook`
- known-bad parent: `2e08667ea202a7d1c8af4ee9aa732ecb614c3b0d`
- fix: `12c4a692ec1ab5309abe0594bccdabe822275fa5`
- commit message: `Prevent onboarding confetti overlay from intercepting pointer events`

The code change adds `pointerEvents: 'none'` to the confetti wrapper and also
stops the confetti after ten seconds.

Fix URL:
`https://github.com/storybookjs/storybook/commit/12c4a692ec1ab5309abe0594bccdabe822275fa5`

### 3. Prekzursil/Reframe

Human fix bundle:

- repository: `Prekzursil/Reframe`
- parent: `9256f58faa3534b13a501823584b4ceb1ec121ab`
- fix/PR merge commit: `8010de7cf12a98b2c99ed2ce4baa6bcadff3ab54`
- PR: `#439`

The commit records a fixed, z-index 1050 secure-keys banner that defaulted to
`pointer-events:auto` and swallowed clicks over native video controls. Its existing
overlay hit-test detector had not exposed the issue on main because stale navigation
timed out before that detector reached its hit test. The repair adds
`pointer-events:none` and a regression check.

Fix URL:
`https://github.com/Prekzursil/Reframe/commit/8010de7cf12a98b2c99ed2ce4baa6bcadff3ab54`

## Four required properties

### Machine perception

The detector measures browser hit-test results for every eligible target and nine
coordinates per target. The useful object is an aggregate target/coordinate/
receiver relation after layout and stacking resolution. A reviewer can manually
inspect a suspect after discovery, but does not practically enumerate the complete
relation across a large surface.

### Asymmetry

Frozen search budget per state:

```text
<= 200 targets
9 initial points / target
<= 1,800 browser hit tests / state
```

Verification of one suspect is nine repeated hit tests plus one independent event
probe in the final protocol. The exact wall-clock ratio is **unbelegt** until the
historical evaluation is run on an unrestricted browser host.

### External oracle

Chromium's rendered hit-test result is external to the detector's classification
logic. For publication-level confirmation the protocol also requires real event
delivery on the historical witness. An LLM is never a verdict source.

### Falsifiability

The candidate dies if it cannot classify all three pinned known-bad/fixed pairs
correctly under the predeclared thresholds, or if a high-confidence false positive
appears in the frozen post-fix control sample.

## Existing tools and why they do not settle the candidate

Browser automation frameworks already contain actionability checks. In Playwright,
for example, an authored click waits until the selected locator receives events.
That is useful but it presupposes a test author selected the control and attempted
that action.

HITMAP's proposed search is different: discover the rendered interactive surface
first, then find controls whose hit relation is impossible before an authored E2E
step exists.

This does **not** establish novelty over all private or unpublished tooling. A claim
that no one has built an equivalent exhaustive browser hit-map system is
**unbelegt**.

## Rejected adjacent candidates

- Screenshot aesthetic scorer — rejected: human judgement is the oracle.
- Axe/Lighthouse wrapper — rejected: prohibited wrapper around an existing scanner.
- Generic visual diff — rejected: expensive verification and baseline judgement.
- Source-level z-index lint — rejected: stacking and event reachability depend on
  rendered runtime, and source heuristics would not provide the required oracle.

## Current status

Prototype classification and browser-control code exists and 17 offline tests pass.
The three historical pre/post browser runs are not yet complete. The available
execution sandbox exposes Chromium 144.0.7559.96 but browser policy blocks local
HTTP and `file:` navigation, so it cannot be used as the historical oracle host.
