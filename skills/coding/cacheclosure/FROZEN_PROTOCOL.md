# Frozen protocol — CacheClosure v0

Frozen before promotion to a SkillQuarry skill. Changing a threshold after
seeing a failure invalidates this protocol version.

## Repositories

1. `KinesisCorporation/Adv360-Pro-ZMK`
   - broken: `962cb1d30eb08e9927cf967eea3c1d3bb5d0d53d`
   - repair: `97f5d7394d36f60754a483bf5551e16d996fe406`
   - expected witness: `hashFiles('manifest-dir/west.yml')` matches zero files;
     the real manifest is `config/west.yml`.

2. `LuvHakii/zuban-wasm-patches`
   - broken: `5bd204092146256b2d89c61781ebe22ef1b0abf8`
   - repair: `193b3b7e8f26e55c02fad17876ab2967382ad484`
   - expected witness: cached `$ROOT/zuban/.patched` suppresses
     `git apply $REPO/patches/*.patch`, while the key hashes only
     `scripts/setup.sh`.

3. `kirpalricky/yapboard`
   - broken: `fd3617018af64f9dd48a383c463b6e7301ec8cd5`
   - repair: `c955411c362f89e1098c8ec5bf556ff1b59daca8`
   - expected historical defect: `.build` contains absolute checkout-dependent
     SwiftPM state while the key did not include repository identity.

## Pass thresholds

- Frozen broken repositories: **3**.
- Required recovered historical defects: **>= 2 / 3**.
- Known defect rank: **top 5 findings per repository**.
- Mechanically verified false positives among `HIGH` findings: **0**.
- Repaired counterparts may retain the known witness: **0**.
- LLM judgement in the oracle: **forbidden**.
- Static scan budget: **<= 30 s per repository**.
- Single minimized witness verification: **<= 60 s**.
- Total frozen suite budget: **<= 2700 s**.
- Peak extra disk during a scan: **<= 5 GiB per repository**.

## Asymmetry gate

The candidate dies if the median cost to verify one minimized witness exceeds
**25%** of the median cost to discover the repository's candidate set.

Local 2026-08-15 measurement on the minimized Zuban historical fixture, 500
iterations:

- full discovery median: **0.688 ms**
- minimized witness verification median: **0.054 ms**
- ratio: **7.9%**

This benchmark is not a production performance claim. CI and real-repository
runtime remain bounded by the limits above.

## Baseline rules

1. Record pre-existing failing commands separately.
2. A pre-existing red command is not detector success.
3. Broken and repaired commits use identical detector configuration.
4. Detector execution may introduce **0** repository modifications.
5. A recovered historical witness must disappear on the corresponding repair.

## What is not claimed

- No claim that every cache key is optimal.
- No claim that every stale-cache failure is detectable statically.
- No generic YAML correctness claim.
- No automatic cache-key rewrite.
- No inference that an arbitrary unkeyed file is causal.
- No support claim for non-GitHub cache providers in v0.
- No detection claim for runtime metadata that is absent from repository files,
  including the frozen Yapboard checkout-path case.
