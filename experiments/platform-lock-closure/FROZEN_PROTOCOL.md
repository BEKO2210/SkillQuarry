# Lock Closure Union — Frozen Protocol v0

Status: **FROZEN BEFORE THE FIRST REPLAY RUN**

## Hypothesis

A committed dependency lock can look internally valid while encoding only the package closure visible from the host that generated it. A supported or actually deployed target platform can therefore require package identities that are absent from the committed lock.

The candidate is only interesting if the missing identity is obtained from the **real package manager's resolution/lock operation**, not inferred from package-name conventions such as `linux`, `darwin`, `arm64`, or `x64`.

## Core invariant

For one unchanged manifest state and the repository's real target platforms:

`union(manager-resolved target closures) ⊆ committed lock closure`

A HIGH witness is a concrete package identity or lock platform entry that the real package manager adds/requires for a real target, but the committed lock does not contain.

A suspicious platform-looking package name by itself is **not** a witness.

## External oracle

Each adapter may translate one manager's native lock representation into package identities, but the manager itself must produce the candidate delta. The detector may not hand-maintain lists of native packages.

For each frozen historical pair:

1. clone the exact revision into a disposable checkout;
2. preserve manifests unchanged;
3. invoke the historical manager family/version against the frozen target context;
4. observe the manager-produced lock delta or strict frozen-lock failure;
5. minimize that delta to the frozen historical witness identity;
6. run the same operation on the repaired revision.

No LLM participates in the verdict.

## Frozen historical pairs

### H1 — npm / FireCMS / macOS-generated lock -> Linux CI

Repository: `firecmsco/firecms`

- broken: `0e8919618a6bcc207e265815cea53ed6c452b5c3`
- fixed: `4e2bfb412c65aa3a131ee8d8ef35f28086d79ebe`
- target: Linux x64 CI
- historical workflow: Node 20, `npm ci`
- lock format: `package-lock.json` lockfileVersion 3
- frozen witness: `node_modules/@rollup/rollup-linux-x64-gnu`
- historical fact: the repair commit says the macOS-generated lock omitted `@rollup/rollup-linux-x64-gnu`, causing Linux `npm ci` failure; the repair changes only `package-lock.json`.

Oracle operation:

- use Node 20 and npm 10;
- from a clean checkout with no `node_modules`, copy the committed lock for comparison;
- run `npm install --package-lock-only --ignore-scripts --include=optional` on Ubuntu x64;
- compare package identities in `packages` before/after;
- broken PASS requires the frozen witness to be newly added by npm;
- fixed PASS requires that witness to already exist and not be newly added.

If npm 10 refuses the historical lock before producing a lock delta for reasons unrelated to the frozen witness, H1 is `INFRA`; the repository may not be replaced.

### H2 — pnpm / cc-candybar / release-host pruning

Repository: `promptctl/cc-candybar`

- broken: `9ad9134f8b685dcc513be5165154d790da15953a`
- fixed: `4d2b7c15970f66b26c339d5bc67307365cc6736c`
- historical toolchain: Node 22, pnpm 10
- frozen manifest identities:
  - `@promptctl/cc-candybar-darwin-arm64@1.0.2`
  - `@promptctl/cc-candybar-linux-arm64@1.0.2`
- historical fact: all four platform packages are declared in `optionalDependencies`; the Linux x64 release regeneration dropped both ARM entries from `pnpm-lock.yaml`. The repair adds `supportedArchitectures` and the two missing lock identities.

Oracle operation:

- use Node 22 and pnpm 10;
- from a clean checkout, copy the committed lock for comparison;
- run `pnpm install --lockfile-only --ignore-scripts --no-frozen-lockfile`;
- compare normalized importer/package identities before/after;
- broken PASS requires at least one of the two frozen ARM identities to be newly added by pnpm;
- fixed PASS requires neither frozen identity to be newly added.

A failure caused only by missing registry/network access is `INFRA`, not PASS.

### H3 — Bundler / personalWebsite / macOS lock -> Linux runner

Repository: `gmackie/personalWebsite`

- broken: `a96f6c8f9c895703cf050faece66918685cfe5ee`
- fixed: `35e335cf0f04ff77e9543da4aebb229e0d308778`
- historical manager: Bundler 2.4.6
- target: `x86_64-linux`
- frozen witnesses:
  - lock platform `x86_64-linux`
  - `ffi (1.17.4-x86_64-linux-gnu)`
  - `google-protobuf (4.34.1-x86_64-linux-gnu)`
  - `sass-embedded (1.98.0-x86_64-linux-gnu)`
- historical fact: the repair is exactly `bundle lock --add-platform x86_64-linux` and adds those seven lock lines.

Oracle operation:

- install/use Bundler 2.4.6;
- copy the committed `Gemfile.lock` for comparison;
- run `bundle _2.4.6_ lock --add-platform x86_64-linux`;
- compare `PLATFORMS` and resolved gem identities before/after;
- broken PASS requires `x86_64-linux` plus at least one frozen Linux gem identity to be newly added by Bundler;
- fixed PASS requires none of the frozen witnesses to be newly added.

## Frozen historical gate

- mandatory historical pairs: **3**
- technically executable pairs required: **3/3**
- recovered broken pairs required: **>= 2/3**
- repaired counterparts retaining a frozen closure witness: **0**
- repository replacements after the first replay: **forbidden**
- manager families represented: **npm, pnpm, Bundler**

A pair counts as recovered only when the package manager itself produces/requires the missing identity. Static presence/absence checks alone do not count.

## Generality death criterion

The shared contract must remain:

`target context -> manager-produced closure delta -> missing committed identity`

If **two or more** mandatory managers require project-specific semantic correctness rules beyond a thin adapter that invokes the package manager and normalizes its lock representation, the candidate dies as an adapter collection.

## Phase 2 gates — only if historical gate passes

Unseen holdout:

- at least 3 unseen historical broken/fixed pairs selected and frozen before their first detector run;
- at least 2 package-manager families represented;
- required recovery: **>= 2/3**;
- repaired counterparts retaining the known witness: **0**.

False positives:

- at least 2 clean controls using already-supported manager adapters;
- mechanically verified HIGH false positives: **0**.

Asymmetry:

- discovery cost = enumerate/resolve all repository-declared or mechanically discovered target closures;
- verification cost = replay one minimized missing-identity witness for one target;
- median verification cost must be **<= 25%** of median discovery candidate-set cost;
- setup, clone, package-manager installation, network warm-up, sleeps, and unrelated build time are excluded from both measurements.

## Budgets

- historical replay <= **2700 s total**;
- peak extra disk <= **5 GiB per target repository**;
- target repositories may only be modified inside disposable checkouts;
- source/manifests may not be patched to manufacture a repair;
- package-manager network access is allowed during the research replay and reported separately; a promoted detector must distinguish dependency metadata acquisition from local closure comparison;
- LLM oracle: **forbidden**.

## Allowed post-freeze corrections

After the first replay, only a genuine invocation/toolchain correction is allowed when all of these remain unchanged:

- repositories and SHAs;
- manager family;
- target platform/context;
- frozen witness identities;
- broken/fixed expected direction;
- thresholds and death criteria.

A real manager-produced no-delta on a broken revision is a **MISS**, not infrastructure. A repaired revision that still produces the frozen witness is a **FAIL**. A historical pair may not be exchanged for an easier repository.

## Non-claims

v0 does not claim every lockfile must contain every platform package in a registry. It does not guess supported platforms from package names. It does not prove the semantic correctness of dependency versions. It does not rewrite lockfiles automatically. It tests only whether a real target closure demonstrably required by the repository is absent from the committed lock.