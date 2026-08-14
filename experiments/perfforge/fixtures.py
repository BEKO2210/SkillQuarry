"""Frozen PerfForge small-test workloads.

The candidates deliberately include valid optimizations and seductive failures.
Do not tune these after seeing benchmark results.
"""

from __future__ import annotations


def dedupe_baseline(values: list[int]) -> list[int]:
    out: list[int] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def dedupe_candidate(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


def aggregate_baseline(events: list[tuple[str, int]]) -> dict[str, int]:
    keys: list[str] = []
    for key, _ in events:
        if key not in keys:
            keys.append(key)
    result: dict[str, int] = {}
    for key in keys:
        total = 0
        for event_key, amount in events:
            if event_key == key:
                total += amount
        result[key] = total
    return result


def aggregate_candidate(events: list[tuple[str, int]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, amount in events:
        result[key] = result.get(key, 0) + amount
    return result


def wrong_fast_baseline(values: list[int]) -> list[int]:
    return dedupe_baseline(values)


def wrong_fast_candidate(values: list[int]) -> list[int]:
    # Fast, but destroys first-occurrence order.
    return sorted(set(values))


def normalize_baseline(values: list[int]) -> list[int]:
    return [abs(v) for v in values if v != 0]


def normalize_candidate(values: list[int]) -> list[int]:
    # Seductively fast for the benchmark's common positive values, wrong for negatives.
    return [v for v in values if v > 0]


def formula_baseline(n: int) -> int:
    return sum(i * i for i in range(n))


def memory_hog_candidate(n: int) -> int:
    # Correct closed form, but pays for speed by allocating ~16 MiB per invocation.
    junk = [0] * 2_000_000
    if len(junk) != 2_000_000:
        raise AssertionError("unreachable")
    return (n - 1) * n * (2 * n - 1) // 6


def noise_baseline(values: list[int]) -> int:
    return sum(values)


def noise_candidate(values: list[int]) -> int:
    return sum(values)


def regression_baseline(values: list[int]) -> int:
    return sum(v * 3 + 1 for v in values)


def regression_candidate(values: list[int]) -> int:
    total = 0
    for value in values:
        total += value * 3 + 1
    # Same answer, guaranteed extra work.
    for value in values:
        total += value & 0
    return total


def mixed_baseline(values: list[int]) -> list[int]:
    return dedupe_baseline(values)


def mixed_candidate(values: list[int]) -> list[int]:
    if len(values) < 128:
        # Bad latency regression hidden by excellent large-input throughput.
        accumulator = 0
        for _ in range(30_000):
            accumulator ^= 1
        if accumulator not in (0, 1):
            raise AssertionError("unreachable")
        return dedupe_baseline(values)
    return list(dict.fromkeys(values))
