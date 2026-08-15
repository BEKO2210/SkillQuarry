# HITMAP test report — prototype branch

Date: 2026-08-15
Status: **PARTIAL — unit prototype passes; historical browser protocol not yet run**

## Environment actually used

```text
Linux 6.18.35 x86_64
Python 3.13.5
Chromium 144.0.7559.96 (Debian trixie build)
```

## Reproduction

```bash
cd skills/ui-ux/hitmap
python3 tests/run_tests.py --min 17
PYTHONPATH=src python3 -m hitmap --version
PYTHONPATH=src python3 -m hitmap doctor
```

Observed locally while preparing this branch:

```text
17 tests passed
hitmap 0.1.0
{"oracle": "chromium", "browser": "/usr/bin/chromium", "status": "available"}
```

## What the 17 tests cover

- nine fixed sample coordinates;
- zero-area rectangle handling;
- deterministic finding IDs;
- ineligible targets suppressed;
- anything other than exactly nine observations suppressed;
- one reachable point suppresses the high-confidence geometry finding;
- 0/9 reachable points produces a finding;
- occluder names are deterministic and deduplicated;
- PASS/FAIL report shape;
- browser discovery through explicit path/name and `HITMAP_BROWSER`.

These tests do not substitute for the external browser oracle.

## Browser preflight attempted

A real Chromium process was launched successfully through the prototype's own
standard-library CDP/WebSocket client. The available sandbox then refused both
`file:` and `http://127.0.0.1` navigation with a managed-browser page stating that
the site/link was blocked by organization policy.

That means this environment cannot honestly run the local historical fixtures or
pinned repositories. The result is **ORACLE ENVIRONMENT UNSUITABLE**, not PASS and
not a product defect in the target repositories.

## Historical protocol status

| Pair | Status |
|---|---|
| nullpoint-descent bad/fixed | NOT RUN |
| Storybook bad/fixed | NOT RUN |
| Reframe bad/fixed | NOT RUN |
| >=200 post-fix observations | NOT RUN |
| real event-delivery confirmation | NOT IMPLEMENTED in 0.1 |

The exact frozen thresholds are in `FROZEN_PROTOCOL.md`.

## Defects found while building the prototype

### D1 — headless Chromium as root never exposed DevTools

Cause: Chromium requires sandbox handling when the process itself runs as root.
The launcher now adds `--no-sandbox` **only** when `os.geteuid() == 0`; normal user
runs retain Chromium's sandbox.

Regression status: the local `doctor`/launch path reaches Chromium after the fix.
A dedicated process-launch test is still missing.

### D2 — WebSocket handshake validator lowercased the accept token

Cause: the first implementation lowercased the complete HTTP response before
comparing the case-sensitive base64 `Sec-WebSocket-Accept` value. A valid Chromium
handshake was rejected.

Fix: parse header names case-insensitively while comparing the header value exactly.
After the fix the CDP page WebSocket connected and `Runtime.evaluate` returned
browser state.

### D3 — test host is policy-blocked

Cause: external managed-browser policy in this execution environment. This is not
worked around. Disabling policy or weakening the browser oracle would make the
historical result less trustworthy.

## Known limits

- No historical pre/post oracle result yet.
- No event-delivery confirmation yet; current findings are geometry-only.
- Chromium only.
- Top-level DOM only; no iframe/shadow-root traversal.
- Native/ARIA/tabindex discovery only; arbitrary JavaScript event listeners can be
  missed.
- No measured wall-clock benchmark against the frozen 120 s/state budget yet.
- No line-coverage percentage is claimed in this branch.

## Promotion rule

Do not change `quality` above `experimental` until every mandatory boundary in
`FROZEN_PROTOCOL.md` passes on an unrestricted browser host.
