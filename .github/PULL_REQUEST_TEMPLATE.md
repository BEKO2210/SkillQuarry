## What this changes

<!-- One paragraph. What moved, and why. -->

## How it was verified

<!-- Commands and their results. "Tests pass" without the command is not evidence. -->

```
```

## Checklist

- [ ] `python3 tools/validate_skills.py` passes
- [ ] `python3 tools/render_readme.py --check` passes (generated blocks not hand-edited)
- [ ] The affected skill's test command passes at its coverage gate
- [ ] New or changed behaviour has a test that fails without the change
- [ ] `TEST_REPORT.md` records any defect found, with cause, fix and regression command
- [ ] No third-party runtime dependency, no network access during install
- [ ] Manifest `version`, `tests` and `permissions` still describe reality

## Deliberately left out

<!-- What you did not do, and why. An honest gap beats a confident guess. -->
