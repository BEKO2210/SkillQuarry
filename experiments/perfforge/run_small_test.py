#!/usr/bin/env python3
"""PerfForge small falsification harness.

The gate accepts an optimization only when:
- all semantic probes match exactly;
- the primary workload has a >=10% bootstrap-lower-bound speedup in wall AND CPU time;
- no workload has >25% median wall-time regression;
- peak traced allocation does not grow by more than 4 MiB.

Thresholds are frozen in SMALL_TEST_PROTOCOL.md before the first CI run.
"""

from __future__ import annotations

import gc
import json
import math
import os
import platform
import random
import statistics
import time
import tracemalloc
from dataclasses import dataclass
from typing import Any, Callable

import fixtures as f

SAMPLES = 13
WARMUPS = 3
BOOTSTRAPS = 2000
MIN_SPEEDUP_LB = 1.10
MAX_WORKLOAD_REGRESSION = 1.25
MAX_EXTRA_PEAK_BYTES = 4 * 1024 * 1024
SEED = 0x5A17F0

Fn = Callable[[Any], Any]


@dataclass(frozen=True)
class Workload:
    name: str
    arg: Any
    loops: int = 1


@dataclass(frozen=True)
class Case:
    name: str
    baseline: Fn
    candidate: Fn
    probes: tuple[Any, ...]
    workloads: tuple[Workload, ...]
    expected: str
    expected_reason: str


def _run(fn: Fn, arg: Any, loops: int) -> Any:
    out = None
    for _ in range(loops):
        out = fn(arg)
    return out


def correctness(case: Case) -> tuple[bool, list[dict[str, Any]]]:
    details = []
    ok = True
    for index, arg in enumerate(case.probes):
        baseline = case.baseline(arg)
        candidate = case.candidate(arg)
        same = baseline == candidate and type(baseline) is type(candidate)
        ok &= same
        details.append({"probe": index, "same": same})
    return ok, details


def measure_pair(case: Case, workload: Workload, rng: random.Random) -> dict[str, Any]:
    for _ in range(WARMUPS):
        _run(case.baseline, workload.arg, workload.loops)
        _run(case.candidate, workload.arg, workload.loops)

    wall_b: list[int] = []
    wall_c: list[int] = []
    cpu_b: list[int] = []
    cpu_c: list[int] = []

    gc.disable()
    try:
        for _ in range(SAMPLES):
            order = ["baseline", "candidate"]
            rng.shuffle(order)
            observed: dict[str, tuple[int, int]] = {}
            for side in order:
                fn = case.baseline if side == "baseline" else case.candidate
                start_wall = time.perf_counter_ns()
                start_cpu = time.process_time_ns()
                _run(fn, workload.arg, workload.loops)
                cpu = time.process_time_ns() - start_cpu
                wall = time.perf_counter_ns() - start_wall
                observed[side] = (wall, cpu)
            wall_b.append(observed["baseline"][0])
            cpu_b.append(observed["baseline"][1])
            wall_c.append(observed["candidate"][0])
            cpu_c.append(observed["candidate"][1])
    finally:
        gc.enable()

    return {
        "name": workload.name,
        "loops": workload.loops,
        "baseline_wall_ns": wall_b,
        "candidate_wall_ns": wall_c,
        "baseline_cpu_ns": cpu_b,
        "candidate_cpu_ns": cpu_c,
    }


def bootstrap_lower_speedup(baseline: list[int], candidate: list[int], seed: int) -> float:
    ratios = [b / c for b, c in zip(baseline, candidate) if c > 0]
    rng = random.Random(seed)
    medians: list[float] = []
    n = len(ratios)
    for _ in range(BOOTSTRAPS):
        sample = [ratios[rng.randrange(n)] for _ in range(n)]
        medians.append(statistics.median(sample))
    medians.sort()
    return medians[max(0, int(0.025 * len(medians)) - 1)]


def peak_bytes(fn: Fn, arg: Any) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        fn(arg)
        _, peak = tracemalloc.get_traced_memory()
        return peak
    finally:
        tracemalloc.stop()


def evaluate(case: Case, case_index: int) -> dict[str, Any]:
    semantic_ok, semantic_details = correctness(case)
    rng = random.Random(SEED + case_index)
    measured = [measure_pair(case, w, rng) for w in case.workloads]

    summarized = []
    for idx, m in enumerate(measured):
        b_wall = m["baseline_wall_ns"]
        c_wall = m["candidate_wall_ns"]
        b_cpu = m["baseline_cpu_ns"]
        c_cpu = m["candidate_cpu_ns"]
        summarized.append(
            {
                "name": m["name"],
                "loops": m["loops"],
                "baseline_wall_median_ns": int(statistics.median(b_wall)),
                "candidate_wall_median_ns": int(statistics.median(c_wall)),
                "wall_speedup_median": statistics.median([b / c for b, c in zip(b_wall, c_wall)]),
                "wall_speedup_lb95": bootstrap_lower_speedup(b_wall, c_wall, SEED + 1000 * case_index + idx),
                "cpu_speedup_lb95": bootstrap_lower_speedup(b_cpu, c_cpu, SEED + 2000 * case_index + idx),
                "median_regression_ratio": statistics.median(c_wall) / statistics.median(b_wall),
            }
        )

    primary = summarized[0]
    primary_fast = (
        primary["wall_speedup_lb95"] >= MIN_SPEEDUP_LB
        and primary["cpu_speedup_lb95"] >= MIN_SPEEDUP_LB
    )
    no_severe_regression = all(
        item["median_regression_ratio"] <= MAX_WORKLOAD_REGRESSION for item in summarized
    )

    memory_arg = case.workloads[0].arg
    baseline_peak = peak_bytes(case.baseline, memory_arg)
    candidate_peak = peak_bytes(case.candidate, memory_arg)
    memory_ok = candidate_peak <= baseline_peak + MAX_EXTRA_PEAK_BYTES

    reasons: list[str] = []
    if not semantic_ok:
        reasons.append("semantic_mismatch")
    if not primary_fast:
        reasons.append("speedup_not_proven")
    if not no_severe_regression:
        reasons.append("workload_regression")
    if not memory_ok:
        reasons.append("memory_regression")

    verdict = "ACCEPT" if not reasons else "REJECT"
    return {
        "name": case.name,
        "expected": case.expected,
        "expected_reason": case.expected_reason,
        "verdict": verdict,
        "matches_expected": verdict == case.expected,
        "correctness": {"pass": semantic_ok, "probes": semantic_details},
        "workloads": summarized,
        "memory": {
            "baseline_peak_bytes": baseline_peak,
            "candidate_peak_bytes": candidate_peak,
            "extra_peak_bytes": candidate_peak - baseline_peak,
            "pass": memory_ok,
        },
        "reasons": reasons,
    }


def build_cases() -> list[Case]:
    dedupe_values = [(i * 37) % 1700 for i in range(6500)]
    aggregate_events = [(f"k{i % 220}", (i * 17) % 13 - 3) for i in range(12_000)]
    wrong_values = [8, 1, 8, 3, 1, 5, 3, 2] * 700
    normalize_values = [i % 97 + 1 for i in range(80_000)]
    noise_values = list(range(80_000))
    regression_values = list(range(70_000))
    mixed_large = [(i * 31) % 1600 for i in range(6000)]
    mixed_small = [5, 3, 5, 2, 3, 1, 4, 1] * 8

    return [
        Case(
            "genuine_dedupe",
            f.dedupe_baseline,
            f.dedupe_candidate,
            ([3, 1, 3, 2, 1], [], [1], [2, 2, 2]),
            (Workload("large", dedupe_values, 1),),
            "ACCEPT",
            "genuine_algorithmic_speedup",
        ),
        Case(
            "genuine_aggregation",
            f.aggregate_baseline,
            f.aggregate_candidate,
            ([("a", 1), ("b", 2), ("a", -1)], [], [("x", 4)]),
            (Workload("events", aggregate_events, 1),),
            "ACCEPT",
            "genuine_algorithmic_speedup",
        ),
        Case(
            "wrong_but_fast",
            f.wrong_fast_baseline,
            f.wrong_fast_candidate,
            ([8, 1, 8, 3, 1], [2, 1, 2], [9, 7, 8]),
            (Workload("large", wrong_values, 1),),
            "REJECT",
            "semantic_mismatch",
        ),
        Case(
            "hidden_edge_case",
            f.normalize_baseline,
            f.normalize_candidate,
            ([1, 2, 3], [-4, 2, 0, -1], [], [0, -2]),
            (Workload("common_positive", normalize_values, 2),),
            "REJECT",
            "semantic_mismatch",
        ),
        Case(
            "memory_for_speed",
            f.formula_baseline,
            f.memory_hog_candidate,
            (10, 1, 1000),
            (Workload("n400k", 400_000, 1),),
            "REJECT",
            "memory_regression",
        ),
        Case(
            "measurement_noise",
            f.noise_baseline,
            f.noise_candidate,
            ([1, 2, 3], [], [9]),
            (Workload("same_implementation", noise_values, 30),),
            "REJECT",
            "speedup_not_proven",
        ),
        Case(
            "true_regression",
            f.regression_baseline,
            f.regression_candidate,
            ([1, 2, 3], [], [-1, 4]),
            (Workload("large", regression_values, 3),),
            "REJECT",
            "speedup_not_proven",
        ),
        Case(
            "benchmark_overfit",
            f.mixed_baseline,
            f.mixed_candidate,
            ([3, 1, 3, 2], [], [1, 1]),
            (
                Workload("large_primary", mixed_large, 1),
                Workload("small_latency", mixed_small, 20),
            ),
            "REJECT",
            "workload_regression",
        ),
    ]


def main() -> int:
    started = time.perf_counter()
    results = [evaluate(case, i) for i, case in enumerate(build_cases())]
    exact = sum(int(r["matches_expected"]) for r in results)
    accepted = [r["name"] for r in results if r["verdict"] == "ACCEPT"]
    rejected = [r["name"] for r in results if r["verdict"] == "REJECT"]
    expected_accept = [r["name"] for r in results if r["expected"] == "ACCEPT"]
    false_accepts = [r["name"] for r in results if r["expected"] == "REJECT" and r["verdict"] == "ACCEPT"]
    false_rejects = [r["name"] for r in results if r["expected"] == "ACCEPT" and r["verdict"] == "REJECT"]

    report = {
        "protocol": {
            "samples": SAMPLES,
            "warmups": WARMUPS,
            "bootstraps": BOOTSTRAPS,
            "min_speedup_lb": MIN_SPEEDUP_LB,
            "max_workload_regression": MAX_WORKLOAD_REGRESSION,
            "max_extra_peak_bytes": MAX_EXTRA_PEAK_BYTES,
            "seed": SEED,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "cases": results,
        "summary": {
            "cases": len(results),
            "exact": exact,
            "accepted": accepted,
            "rejected": rejected,
            "expected_accept": expected_accept,
            "false_accepts": false_accepts,
            "false_rejects": false_rejects,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        },
        "verdict": "PASS_SMALL" if exact == len(results) and not false_accepts and not false_rejects else "FAIL_SMALL",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["verdict"] == "PASS_SMALL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
