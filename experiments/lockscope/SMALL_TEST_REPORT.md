# LockScope small evaluation

Date: 2026-08-14
Branch: `test/lockscope-small-20260814-v2`
Workflow run: `31815809106`
Job: `94817079943`
Verdict: **PASS_SMALL**

## Scope

This is a small falsifiable concept test, not a production parser or repair proof.
It evaluates whether a lock-scope analyzer can distinguish real async contention
patterns from common false positives and whether the classification tracks a
historical real-world Javis concurrency repair.

Pinned Javis commits:

- before: `f0d6b556f459a3757b15e13fde3f5198b7d0826e`
- after: `26f6e5db1d47af58e814809505929fa0c16ae1eb`

Because the historical fix was already known from earlier work, this is **not**
claimed as a blind patch-recovery test. The pass criteria are independent lock
invariants, not textual similarity to the later patch.

## Frozen matrix

10/10 cases passed:

1. short async lock scope -> quiet
2. guard's last use before later `.await` -> quiet (NLL approximation)
3. explicit `drop(guard)` before `.await` -> quiet
4. Tokio exclusive lock live across `.await` -> high
5. `std::sync::Mutex` live across `.await` -> critical
6. A->B / B->A acquisition graph -> lock-order cycle detected
7. consistent A->B order -> no cycle
8. `RwLock` read guard live across `.await` -> medium, not exclusive
9. historical Javis pre-fix bottleneck -> detected, no invented deadlock
10. historical Javis post-fix transition -> original exclusive recall bottleneck gone, remaining long read-lock scope retained as medium risk

## Javis measurements

Historical pre-fix `run_recall`:

```text
mode: exclusive
lock: self.inner
awaits while guard live: 4
span: 42 lines
classification:
  exclusive_lock_across_await / high
  large_exclusive_critical_section / high
lock-order cycles: none
```

Historical pre-fix `run_train`:

```text
mode: exclusive
awaits while guard live: 4
span: 87 lines
classification:
  exclusive_lock_across_await / high
  large_exclusive_critical_section / high
```

Historical pre-fix `save_to_file`:

```text
mode: exclusive
awaits while guard live: 0
span: 14 lines
```

This negative result matters: the function later performs async file I/O, but
the lock guard is no longer used by then. LockScope did not report an
await-under-lock merely because `.await` occurs later in the lexical function.

Historical post-fix `run_recall`:

```text
mode: read
awaits while guard live: 4
span: 44 lines
classification:
  read_lock_across_await / medium
exclusive recall finding: gone
lock-order cycles: none
```

That is the desired distinction: the historical architecture removed the
single-writer recall serialization, while a long read lock can still delay
writers and remains a lower-severity optimization opportunity.

The historical Claude commit reports the real performance consequence of the
architectural repair: recall throughput increased from ~141 ops/s plateau to
~358-359 ops/s at high concurrency (~2.5x). That result is an oracle/reference,
not a measurement produced by this small analyzer test.

## What this establishes

The core diagnostic idea is useful enough to continue:

- lock lifetime matters more than merely finding `Mutex` tokens;
- NLL/explicit-drop false positives can be avoided in common forms;
- lock-order cycles can be separated from contention warnings;
- exclusive and shared async lock scopes need different severity;
- the classifier aligns with a known real-world Rust concurrency bottleneck and its later architectural repair.

## What it does NOT establish

The current prototype is intentionally textual/brace-balanced. It is not ready
for SkillQuarry production use.

Missing proof:

- rust-analyzer or Rust AST-backed acquisition/guard resolution;
- aliases, macros, helper-returned guards, methods split across files;
- parking_lot and other synchronization libraries;
- >2-node lock-order cycles;
- control-flow-sensitive lifetimes across branches/loops/early returns;
- generated repair patches;
- compiler/test validation of an automatically generated repair;
- measured contention/latency before and after a LockScope-produced patch.

## Decision

```text
concept:        GO
small test:     PASS_SMALL (10/10)
production:     NOT YET
next test:      parser-backed real-repo audit + generated repair proof
```
