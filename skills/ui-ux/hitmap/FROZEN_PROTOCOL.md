# HITMAP frozen evaluation protocol

Frozen: 2026-08-15, before historical implementation evaluation.

Changing a threshold below after seeing historical results invalidates the run and
requires a new protocol version that is reported separately.

## Claim under test

HITMAP can mechanically detect a visible, enabled interactive target whose sampled
interior area is completely unreachable to pointer hit testing because another
rendered element wins every sampled coordinate.

It does not claim general UX correctness, accessibility compliance, cross-browser
coverage or detection of every occlusion defect.

## Pinned historical oracle pairs

| Repository | Known-bad SHA | Human fix SHA |
|---|---|---|
| `runshu-W/nullpoint-descent` | `6c631160971cc97ac74d24aa133b7eb003116a76` | `5dc0df1a1ad6ba3f3062d87bc2529953124bb471` |
| `storybookjs/storybook` | `2e08667ea202a7d1c8af4ee9aa732ecb614c3b0d` | `12c4a692ec1ab5309abe0594bccdabe822275fa5` |
| `Prekzursil/Reframe` | `9256f58faa3534b13a501823584b4ceb1ec121ab` | `8010de7cf12a98b2c99ed2ce4baa6bcadff3ab54` |

No repository or SHA may be substituted after results are seen.

## Target eligibility

A target is eligible when discovered through one of:

```text
button/input/select/textarea/a[href]
role=button|link|checkbox|radio|switch|menuitem|tab
explicit tabindex
```

Exclude mechanically when any is true:

```text
disabled
aria-disabled=true
aria-hidden=true
inside inert subtree
display:none
visibility:hidden
opacity exactly 0
bounding area < 16 px²
entire rectangle outside viewport
```

## Sampling rule

Exactly nine coordinates in the target rectangle:

```text
(50%,50%)
(20%,20%) (80%,20%) (20%,80%) (80%,80%)
(50%,20%) (80%,50%) (50%,80%) (20%,50%)
```

A point is reachable only if the first pointer-receiving hit-test result is:

```text
the target
OR a descendant of the target
OR an associated label / descendant of that label
```

## Geometry finding threshold

Report the historical witness only when:

```text
eligible = true
sample count = 9
reachable count = 0
```

One reachable point suppresses the finding.

## Publication-level confirmation

For each of the three known-bad witnesses, a second independent browser action must
dispatch the pointer at the historical interaction coordinate and record that the
intended target did not receive the event before the fix and does receive it after
the fix.

The generic 0.1 scanner does not automate this step yet. Therefore its findings
must remain labelled `geometry` and the skill remains `experimental`.

## Pass boundaries

The candidate is promoted only if all are true:

1. 3/3 known-bad SHAs produce the expected witness finding.
2. 3/3 corresponding human-fixed SHAs do not produce that witness finding.
3. Historical pair classification is 6/6 correct.
4. At least 200 eligible target/state observations are collected on the three
   post-fix revisions combined.
5. High-confidence false positives in those post-fix observations = 0.
6. Two consecutive runs on each pinned state produce identical finding IDs.
7. Missing browser oracle returns `ORACLE_UNAVAILABLE`, never PASS.
8. No screenshot model or LLM participates in the verdict.
9. The detector modifies no target repository file.
10. After pinned repositories/dependencies are prepared, detector network access is
    limited to the explicitly scanned local application endpoint.

Failure of 1–5 kills the candidate. It must not be published as `tested` by
softening a threshold.

## Runtime budget

Measured after each target application is already built and server-ready:

```text
one state scan:        <= 120 s
three-repository set:  <= 360 s detector runtime
```

Build/install time is recorded separately.

These wall-clock budgets are frozen but currently **unbelegt** by historical
measurement.

## Search budget

```text
maximum states per repository       64
maximum eligible targets per state  200
sample points per target              9
maximum initial hit tests/state    1,800
maximum confirmation actions         20
```

A run exceeding a budget is INCOMPLETE, not PASS.

## Baseline accounting

Pre-existing red tests are recorded before HITMAP runs and do not count as detector
success.

For nullpoint-descent the human fix documents 113 tests and seven walkthroughs that
were green while the first user interaction was unreachable because all automated
walkthroughs used `?demo=1`.

For Reframe the human fix documents that an existing overlay hit-test spec did not
reach its hit-test on main because stale navigation timed out first. That unrelated
red state must not be re-labelled as a HITMAP hit.

Whole-repository pre-fix CI status for Storybook is not asserted here.

## Negative controls

Do not report:

- disabled controls;
- `aria-disabled=true` controls;
- background controls intentionally made inert;
- fully hidden controls;
- decorative overlays with `pointer-events:none` when the underlying target is
  reachable;
- a partially occluded target with at least one reachable sampled point.

## Not claimed

```text
not an accessibility audit
not WCAG compliance
not a visual-regression system
not a UX quality score
not a replacement for authored E2E tests
not proof that a reachable control behaves correctly
not keyboard/touch coverage
not cross-browser equivalence
not detection of all overlay defects
```
